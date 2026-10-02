"""Conversation and message service.

Ownership rule: every read and write scopes by the calling user's Twin. A
client cannot read another user's conversation even by guessing an id — the
join to `twins.user_id` returns nothing and we surface a plain 404.

Sprint 2 addition: after persisting a (user, twin) turn pair, enqueue a
background task that extracts memory candidates. The task:
- opens its own DB session (does not share this request's session),
- never raises back into the caller,
- never writes to `TwinProfile`.

The chat response is returned to the user BEFORE the extraction task
runs; a slow or failing extractor cannot slow or fail chat.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.common.errors import NotFoundError
from app.common.tasks import TaskRunner
from app.conversation.models import Conversation, Message
from app.conversation.pipeline import run_pipeline
from app.conversation.schemas import ConversationCreateIn
from app.llm.interface import LLMProvider
from app.memory.tasks import extract_memory_candidates_task
from app.observability.logging import get_logger
from app.twin.models import Twin

logger = get_logger(__name__)


class ConversationNotFoundError(NotFoundError):
    code = "conversation_not_found"


class ConversationService:
    def __init__(
        self,
        session: AsyncSession,
        provider: LLMProvider,
        *,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        llm_model: str | None = None,
        task_runner: TaskRunner | None = None,
        extraction_provider: LLMProvider | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        self._sessionmaker = sessionmaker
        self._llm_model = llm_model
        self._task_runner = task_runner
        # Falls back to the chat provider only when extraction_provider is
        # not wired at all (stripped unit test). Production injects both.
        self._extraction_provider = extraction_provider or provider

    async def list_for_twin(self, twin: Twin) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.twin_id == twin.id)
            .order_by(Conversation.updated_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars())

    async def get(self, twin: Twin, conversation_id: uuid.UUID) -> Conversation:
        stmt = (
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.twin_id == twin.id,
            )
            .options(selectinload(Conversation.messages))
        )
        conv = (await self._session.execute(stmt)).scalar_one_or_none()
        if conv is None:
            raise ConversationNotFoundError(
                "Conversation not found or not yours.",
                details={"conversation_id": str(conversation_id)},
            )
        return conv

    async def create(self, twin: Twin, payload: ConversationCreateIn) -> Conversation:
        conv = Conversation(twin_id=twin.id, title=payload.title)
        self._session.add(conv)
        await self._session.flush()
        await self._session.commit()
        await self._session.refresh(conv)
        logger.info(
            "conversation.created",
            conversation_id=str(conv.id),
            twin_id=str(twin.id),
        )
        return conv

    async def list_messages(self, twin: Twin, conversation_id: uuid.UUID) -> list[Message]:
        conv = await self.get(twin, conversation_id)
        return list(conv.messages)

    async def post_message(
        self,
        twin: Twin,
        conversation_id: uuid.UUID,
        content: str,
    ) -> tuple[Message, Message]:
        """Persist the user turn, run the pipeline, persist the twin turn.

        After persistence commits, enqueues memory extraction. Enqueueing is
        best-effort: if no `TaskRunner` was wired (unlikely in production,
        possible in a stripped unit test), extraction is simply skipped.
        """
        conv = await self.get(twin, conversation_id)

        user_msg = Message(
            conversation_id=conv.id,
            role="user",
            content=content,
        )
        self._session.add(user_msg)
        await self._session.flush()
        await self._session.refresh(user_msg)

        # History excludes the just-added user_msg — appended inside the
        # pipeline so the shape stays provider-agnostic.
        history = [m for m in conv.messages if m.id != user_msg.id]
        response = await run_pipeline(
            twin=twin,
            conversation=conv,
            history=history,
            user_message_content=content,
            provider=self._provider,
        )

        twin_msg = Message(
            conversation_id=conv.id,
            role="twin",
            content=response.content,
            llm_provider=response.provider,
            llm_model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            metadata_json={"finish_reason": response.finish_reason},
        )
        self._session.add(twin_msg)
        await self._session.commit()
        await self._session.refresh(user_msg)
        await self._session.refresh(twin_msg)

        logger.info(
            "conversation.message.persisted",
            conversation_id=str(conv.id),
            twin_id=str(twin.id),
            user_message_id=str(user_msg.id),
            twin_message_id=str(twin_msg.id),
            provider=response.provider,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        # Sprint 2 hook: extract memory candidates in the background.
        self._enqueue_memory_extraction(
            twin=twin,
            conversation_id=conv.id,
            user_message_id=user_msg.id,
            twin_message_id=twin_msg.id,
        )

        return user_msg, twin_msg

    def _enqueue_memory_extraction(
        self,
        *,
        twin: Twin,
        conversation_id: uuid.UUID,
        user_message_id: uuid.UUID,
        twin_message_id: uuid.UUID,
    ) -> None:
        if (
            self._task_runner is None
            or self._sessionmaker is None
            or self._llm_model is None
        ):
            logger.info(
                "memory.extraction.not_enqueued",
                reason="runner_not_wired",
                conversation_id=str(conversation_id),
            )
            return
        self._task_runner.enqueue(
            extract_memory_candidates_task,
            sessionmaker=self._sessionmaker,
            llm_provider=self._extraction_provider,
            llm_model=self._llm_model,
            user_id=twin.user_id,
            twin_id=twin.id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            twin_message_id=twin_message_id,
        )
