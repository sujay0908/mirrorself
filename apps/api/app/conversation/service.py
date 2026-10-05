"""Conversation and message service.

Ownership rule: every read and write scopes by the calling user's Twin. A
client cannot read another user's conversation even by guessing an id — the
join to `twins.user_id` returns nothing and we surface a plain 404.

Sprint 2 added background memory candidate extraction after each turn.
Sprint 3 adds memory retrieval BEFORE each turn: the service asks the
retriever for relevant confirmed memories, hands the ranked result to the
context builder, and passes a populated `TwinContext` to the pipeline.

Two hard invariants (Sprint 3 architectural rules F + E):

- Memory retrieval failure MUST NOT fail the chat response. The service
  catches any exception from the retriever, logs it with IDs, and falls
  back to an empty-memory context so the Twin can still respond.
- Memory extraction failure MUST NOT fail the chat response (preserved
  from Sprint 2 — the background task is already isolated).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.common.errors import NotFoundError
from app.common.tasks import TaskRunner
from app.conversation.intent import (
    DEFAULT_INTENT_DETECTOR,
    Intent,
    IntentDetector,
    IntentResult,
    detect_intent_safely,
)
from app.conversation.models import Conversation, Message
from app.conversation.pipeline import run_pipeline
from app.conversation.policy import ContextPolicy, policy_for
from app.conversation.schemas import ConversationCreateIn
from app.conversation.state import TwinState
from app.goal.models import Goal
from app.goal.service import GoalService
from app.llm.interface import LLMProvider
from app.memory.context import ContextBuilder, TwinContext
from app.memory.retrieval import MemoryRetriever, RetrievalResult
from app.memory.tasks import extract_memory_candidates_task
from app.observability.logging import get_logger
from app.twin.models import Twin

logger = get_logger(__name__)


class ConversationNotFoundError(NotFoundError):
    code = "conversation_not_found"


class ConversationService:
    # Sprint 4 (DF8): a hard cap on the number of active goals carried into
    # the prompt per turn. Kept as a service-layer constant so the
    # ContextBuilder's `max_active_goals` and the goal query stay aligned.
    _MAX_ACTIVE_GOALS_IN_CONTEXT: int = 3

    def __init__(
        self,
        session: AsyncSession,
        provider: LLMProvider,
        *,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        llm_model: str | None = None,
        task_runner: TaskRunner | None = None,
        extraction_provider: LLMProvider | None = None,
        retriever: MemoryRetriever | None = None,
        context_builder: ContextBuilder | None = None,
        goal_service: GoalService | None = None,
        intent_detector: IntentDetector | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        self._sessionmaker = sessionmaker
        self._llm_model = llm_model
        self._task_runner = task_runner
        self._extraction_provider = extraction_provider or provider
        self._retriever = retriever
        self._context_builder = context_builder or ContextBuilder()
        self._goal_service = goal_service
        self._intent_detector = intent_detector or DEFAULT_INTENT_DETECTOR

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
        """Persist the user turn, retrieve relevant memory, run the pipeline,
        persist the twin turn, enqueue extraction.

        Retrieval and extraction are both best-effort. A failing retriever
        yields an empty-memory context (chat still works). A failing
        extractor is handled in the background task.
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

        history = [m for m in conv.messages if m.id != user_msg.id]

        # Sprint 6: intent detection and context policy FIRST. The
        # resolved policy drives the retriever's `limit`, the goal
        # service's `limit`, and the ContextBuilder's budget — so a
        # casual TALK pulls fewer memories than a deep REFLECT, without
        # any downstream code learning about intents.
        intent_result = await self._detect_intent_safely(
            user_message=content,
            conversation_id=conv.id,
            twin=twin,
        )
        policy = self._policy_for_intent_safely(
            intent_result=intent_result,
            conversation_id=conv.id,
            twin=twin,
        )
        twin_state = TwinState(intent_result=intent_result, policy=policy)

        retrieval = await self._retrieve_safely(
            twin=twin,
            query_text=content,
            conversation_id=conv.id,
            limit=policy.memory_limit,
        )
        active_goals, goals_ok, goals_error = await self._load_active_goals_safely(
            twin=twin,
            conversation_id=conv.id,
            limit=policy.goal_limit,
        )
        twin_context: TwinContext = self._context_builder.build(
            twin=twin,
            retrieved=retrieval.items,
            recent_messages=history,
            active_goals=active_goals,
            budget=policy.context_budget(),
        )

        response = await run_pipeline(
            context=twin_context,
            user_message_content=content,
            provider=self._provider,
            twin_state=twin_state,
        )

        twin_msg = Message(
            conversation_id=conv.id,
            role="twin",
            content=response.content,
            llm_provider=response.provider,
            llm_model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            metadata_json={
                "finish_reason": response.finish_reason,
                "retrieval": {
                    "ok": retrieval.ok,
                    "error": retrieval.error,
                    "memories_returned": len(retrieval.items),
                    "memory_ids": [str(r.memory.id) for r in retrieval.items],
                },
                "goals_context": {
                    "ok": goals_ok,
                    "error": goals_error,
                    "goals_used": len(active_goals),
                    "goal_ids": [str(g.id) for g in active_goals],
                },
                "twin_state": twin_state.to_metadata(),
            },
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
            retrieval_ok=retrieval.ok,
            memories_used=len(retrieval.items),
            goals_ok=goals_ok,
            goals_used=len(active_goals),
            intent=intent_result.intent.value,
            intent_confidence=intent_result.confidence,
            intent_reason=intent_result.reason,
            memory_limit=policy.memory_limit,
            goal_limit=policy.goal_limit,
            history_turns=policy.history_turns,
        )

        self._enqueue_memory_extraction(
            twin=twin,
            conversation_id=conv.id,
            user_message_id=user_msg.id,
            twin_message_id=twin_msg.id,
        )

        return user_msg, twin_msg

    async def _detect_intent_safely(
        self,
        *,
        user_message: str,
        conversation_id: uuid.UUID,
        twin: Twin,
    ) -> IntentResult:
        """Run the intent detector; absorb any failure.

        Sprint 6: intent-detection failure MUST NOT fail chat. The
        detector itself already never raises (see
        `app.conversation.intent.detect_intent_safely`); this method
        adds a second belt-and-braces try/except so a future
        contributor who accidentally relaxes that invariant does not
        break the chat path. On any failure we return UNKNOWN.
        """
        try:
            result = await detect_intent_safely(self._intent_detector, user_message)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "intent.detection.unhandled",
                error=type(exc).__name__,
                conversation_id=str(conversation_id),
                twin_id=str(twin.id),
            )
            return IntentResult(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                reason=f"unhandled:{type(exc).__name__}",
            )
        if result.intent is Intent.UNKNOWN:
            logger.info(
                "intent.detection.unknown",
                reason=result.reason,
                conversation_id=str(conversation_id),
                twin_id=str(twin.id),
            )
        return result

    def _policy_for_intent_safely(
        self,
        *,
        intent_result: IntentResult,
        conversation_id: uuid.UUID,
        twin: Twin,
    ) -> ContextPolicy:
        """Resolve the context policy; absorb any failure.

        Sprint 6: context-policy failure MUST NOT fail chat. The
        `policy_for` function itself is pure and never raises today,
        but keep the wrapping so a future tweak that reads config or
        a DB cannot regress the invariant.
        """
        try:
            return policy_for(intent_result.intent)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "intent.policy.unhandled",
                error=type(exc).__name__,
                conversation_id=str(conversation_id),
                twin_id=str(twin.id),
            )
            return policy_for(Intent.UNKNOWN)

    async def _retrieve_safely(
        self,
        *,
        twin: Twin,
        query_text: str,
        conversation_id: uuid.UUID,
        limit: int,
    ) -> RetrievalResult:
        """Call the retriever and absorb any failure.

        The retriever ITSELF never raises (it catches internally and sets
        `error`). This method adds a second belt-and-braces try/except in
        case a future contributor accidentally changes that invariant.

        Sprint 6: `limit` is passed in by the caller based on the
        resolved `ContextPolicy`. A `limit` of 0 means the policy
        decided no memories should be retrieved for this intent — we
        short-circuit to an empty success result rather than calling
        the retriever at all.
        """
        if self._retriever is None:
            logger.info(
                "memory.retrieval.skipped",
                reason="retriever_not_wired",
                conversation_id=str(conversation_id),
                twin_id=str(twin.id),
            )
            return RetrievalResult(metadata={"skipped": True, "reason": "retriever_not_wired"})
        if limit <= 0:
            logger.info(
                "memory.retrieval.skipped",
                reason="policy_memory_zero",
                conversation_id=str(conversation_id),
                twin_id=str(twin.id),
            )
            return RetrievalResult(metadata={"skipped": True, "reason": "policy_memory_zero"})
        try:
            result = await self._retriever.retrieve(twin, query_text, limit=limit)
        except Exception as exc:
            logger.warning(
                "memory.retrieval.unhandled",
                error=type(exc).__name__,
                conversation_id=str(conversation_id),
                twin_id=str(twin.id),
            )
            return RetrievalResult(
                error=f"unhandled:{type(exc).__name__}",
                metadata={
                    "conversation_id": str(conversation_id),
                    "twin_id": str(twin.id),
                },
            )
        if result.error:
            logger.warning(
                "memory.retrieval.failed",
                reason=result.error,
                conversation_id=str(conversation_id),
                twin_id=str(twin.id),
                metadata=result.metadata,
            )
        return result

    async def _load_active_goals_safely(
        self,
        *,
        twin: Twin,
        conversation_id: uuid.UUID,
        limit: int,
    ) -> tuple[list[Goal], bool, str | None]:
        """Load active goals for the TwinContext; never fail chat on error.

        Returns (goals, ok, error). An empty list + ok=True is the common
        path (no goals yet). An empty list + ok=False means loading failed
        and the chat continues without goal context.

        Sprint 6: `limit` is passed in by the caller based on the
        resolved `ContextPolicy`. A `limit` of 0 means the policy
        decided no goals should be included for this intent — we
        short-circuit to an empty success result.
        """
        if self._goal_service is None:
            logger.info(
                "goals.context.skipped",
                reason="service_not_wired",
                conversation_id=str(conversation_id),
                twin_id=str(twin.id),
            )
            return [], True, None
        if limit <= 0:
            logger.info(
                "goals.context.skipped",
                reason="policy_goals_zero",
                conversation_id=str(conversation_id),
                twin_id=str(twin.id),
            )
            return [], True, None
        try:
            goals = await self._goal_service.list_active_for_context(twin, limit=limit)
            return list(goals), True, None
        except Exception as exc:
            logger.warning(
                "goals.context.failed",
                error=type(exc).__name__,
                conversation_id=str(conversation_id),
                twin_id=str(twin.id),
            )
            return [], False, f"unhandled:{type(exc).__name__}"

    def _enqueue_memory_extraction(
        self,
        *,
        twin: Twin,
        conversation_id: uuid.UUID,
        user_message_id: uuid.UUID,
        twin_message_id: uuid.UUID,
    ) -> None:
        if self._task_runner is None or self._sessionmaker is None or self._llm_model is None:
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
