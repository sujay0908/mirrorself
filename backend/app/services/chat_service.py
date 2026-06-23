"""
Top-level orchestrator. Wires sentiment -> prompt -> LLM -> voice -> avatar
-> memory into a single async pipeline.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.schemas.chat import ChatResponse, MessageOut
from app.services.avatar_service import avatar_service
from app.services.llm_service import llm_service
from app.services.memory_service import memory_service
from app.services.prompt_service import build_system_prompt
from app.services.sentiment import sentiment_analyzer
from app.services.storage_service import storage_service
from app.services.voice_service import voice_service


class ChatService:
    async def ensure_conversation(
        self, db: AsyncSession, user: User, conversation_id: Optional[int]
    ) -> Conversation:
        if conversation_id:
            conv = (
                await db.execute(
                    select(Conversation).where(
                        Conversation.id == conversation_id, Conversation.user_id == user.id
                    )
                )
            ).scalar_one_or_none()
            if conv:
                return conv
        conv = Conversation(user_id=user.id, title=None)
        db.add(conv)
        await db.flush()
        return conv

    async def get_history(
        self, db: AsyncSession, conversation_id: int, limit: int = 12
    ) -> list[dict]:
        rows = (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        rows = list(reversed(rows))
        return [{"role": m.role, "content": m.content} for m in rows]

    async def chat(
        self,
        db: AsyncSession,
        user: User,
        message: str,
        conversation_id: Optional[int] = None,
        twin_mode: bool = False,
    ) -> ChatResponse:
        # 1. Ensure conversation
        conv = await self.ensure_conversation(db, user, conversation_id)

        # 2. Sentiment / emotion analysis (deep path for chat)
        sentiment = await sentiment_analyzer.deep(message)
        logger.info(f"[user {user.id}] emotion={sentiment.emotion} tone={sentiment.tone}")

        # 3. Build prompt with personality + facts
        durable_facts = await memory_service.get_durable_facts(db, user.id, limit=30)
        recent_redis = await memory_service.get_recent_facts(user.id, limit=30)
        merged = await memory_service.merge(user, recent_redis, durable_facts)
        system = build_system_prompt(user, facts=merged, tone=sentiment.tone, twin_mode=twin_mode)

        # 4. Build history
        history = await self.get_history(db, conv.id, limit=12)
        messages = history + [{"role": "user", "content": message}]

        # 5. Persist user message
        user_msg = Message(
            conversation_id=conv.id,
            role="user",
            content=message,
            detected_emotion=sentiment.emotion,
        )
        db.add(user_msg)
        await db.flush()

        # 6. Push to short-term memory
        await memory_service.push_short_term(user.id, "user", message)

        # 7. Generate AI reply
        assistant_text = await llm_service.chat(system=system, messages=messages)

        # 8. Synthesise voice + avatar (in parallel with fact extraction)
        voice_task = asyncio.create_task(
            voice_service.synthesize(user.voice_id, assistant_text)
        )
        fact_task = asyncio.create_task(
            llm_service.extract_facts(message, assistant_text)
        )
        audio_path, new_facts_raw = await asyncio.gather(voice_task, fact_task)

        # Upload audio to Supabase Storage
        audio_object_path: Optional[str] = None
        if audio_path:
            try:
                with open(audio_path, "rb") as f:
                    audio_data = f.read()
                filename = Path(audio_path).name
                audio_object_path = await storage_service.upload_voice_output(
                    user.id, audio_data, filename
                )
            except Exception as e:
                logger.error(f"Failed to upload audio: {e}")

        # 9. Optional avatar (only if user has a face photo)
        video_object_path: Optional[str] = None
        if user.face_photo_path and user.twin_status == "ready":
            # Download face photo for processing
            face_local = await storage_service.download_for_processing(
                "face-photos", user.face_photo_path
            )
            video_path = await avatar_service.generate_talking_head(
                face_local, audio_path, user.id
            )
            
            # Upload video to Supabase Storage
            if video_path:
                try:
                    with open(video_path, "rb") as f:
                        video_data = f.read()
                    filename = Path(video_path).name
                    video_object_path = await storage_service.upload_avatar_video(
                        user.id, video_data, filename
                    )
                except Exception as e:
                    logger.error(f"Failed to upload video: {e}")

        # 10. Persist assistant message
        assistant_msg = Message(
            conversation_id=conv.id,
            role="assistant",
            content=assistant_text,
            detected_emotion=sentiment.emotion,
            response_tone=sentiment.tone,
            audio_path=audio_object_path,
            video_path=video_object_path,
        )
        db.add(assistant_msg)
        await db.flush()

        # 11. Memory: write extracted facts (durable + cache)
        new_facts: list[str] = []
        for f in new_facts_raw[:5]:
            fact = await memory_service.add_fact(
                db=db,
                user_id=user.id,
                category=f.get("category", "personal"),
                content=f.get("content", ""),
                confidence=0.8,
                source=f"conv:{conv.id}",
            )
            if fact:
                new_facts.append(fact.content)

        await memory_service.push_short_term(user.id, "assistant", assistant_text)
        user.conversation_count = (user.conversation_count or 0) + 1
        if not conv.title and user.conversation_count <= 1:
            conv.title = message[:60]

        return ChatResponse(
            conversation_id=conv.id,
            user_message=MessageOut.model_validate(user_msg),
            assistant_message=MessageOut.model_validate(assistant_msg),
            new_facts=new_facts,
        )


chat_service = ChatService()
