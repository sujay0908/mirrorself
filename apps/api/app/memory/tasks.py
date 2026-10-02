"""Background task for extracting memory candidates from a chat turn.

Hard guarantees (asserted by `test_extraction_failure_does_not_fail_chat`):

- Runs AFTER the chat response has been persisted and returned to the user.
- Opens its own DB session so it does not share the request lifecycle.
- Never raises back to the chat path (chat has already returned 201 by the
  time this task runs via FastAPI `BackgroundTasks`).
- Logs failure with conversation + message IDs ONLY — never any content.
- On any failure, no partial memory candidate persists.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.conversation.models import Message
from app.llm.interface import LLMProvider
from app.memory.extractor import ExtractionResult, MemoryExtractor
from app.memory.service import MemoryService
from app.observability.logging import get_logger
from app.twin.models import Twin, TwinProfile

logger = get_logger(__name__)


async def extract_memory_candidates_task(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    llm_provider: LLMProvider,
    llm_model: str,
    user_id: uuid.UUID,
    twin_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_message_id: uuid.UUID,
    twin_message_id: uuid.UUID,
) -> None:
    log_ctx = {
        "conversation_id": str(conversation_id),
        "user_message_id": str(user_message_id),
        "twin_message_id": str(twin_message_id),
        "twin_id": str(twin_id),
    }
    try:
        async with sessionmaker() as session:
            msg_stmt = select(Message).where(
                Message.id.in_([user_message_id, twin_message_id])
            )
            rows = {m.id: m for m in (await session.execute(msg_stmt)).scalars()}
            user_msg = rows.get(user_message_id)
            twin_msg = rows.get(twin_message_id)
            if user_msg is None or twin_msg is None:
                logger.warning(
                    "memory.extraction.failed",
                    reason="missing_messages",
                    **log_ctx,
                )
                return

            twin = (
                await session.execute(select(Twin).where(Twin.id == twin_id))
            ).scalar_one_or_none()
            if twin is None:
                logger.warning(
                    "memory.extraction.failed",
                    reason="missing_twin",
                    **log_ctx,
                )
                return

            profile = (
                await session.execute(
                    select(TwinProfile).where(TwinProfile.twin_id == twin_id)
                )
            ).scalar_one_or_none()

            extractor = MemoryExtractor(llm_provider, llm_model)
            result: ExtractionResult = await extractor.extract(
                user_message=user_msg.content,
                twin_response=twin_msg.content,
                twin_profile=profile,
            )

            if result.error is not None:
                logger.warning(
                    "memory.extraction.failed",
                    reason=result.error,
                    **log_ctx,
                )
                return

            if not result.drafts:
                logger.info("memory.extraction.empty", **log_ctx)
                return

            service = MemoryService(session, embedding_provider=None)
            await service.create_candidates(
                twin,
                result.drafts,
                source_conversation_id=conversation_id,
                source_message_id=user_message_id,
            )
            logger.info(
                "memory.extraction.persisted",
                drafts=len(result.drafts),
                **log_ctx,
            )
    except Exception as exc:
        # Last line of defence: anything slips past the inner handlers lands
        # here and is logged. The chat response has already shipped — this
        # cannot affect the user's turn.
        logger.exception(
            "memory.extraction.failed",
            reason=f"unhandled:{type(exc).__name__}",
            **log_ctx,
        )
