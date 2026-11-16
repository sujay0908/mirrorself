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

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import utcnow
from app.common.errors import ConflictError, NotFoundError
from app.common.ids import new_id
from app.common.tasks import TaskRunner
from app.config import Settings
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
from app.evolution.acknowledgement import ACK_SURFACE_LIMIT, compose_learning
from app.evolution.locks import acquire_twin_evolution_lock
from app.evolution.service import EvolutionService
from app.goal.models import Goal
from app.goal.service import GoalService
from app.llm.interface import LLMProvider
from app.llm.registry import ProviderNotConfiguredError
from app.memory.context import ContextBuilder, TwinContext
from app.memory.retrieval import MemoryRetriever, RetrievalResult
from app.memory.tasks import extract_memory_candidates_task
from app.observability.logging import get_logger
from app.reflection.tasks import scheduled_reflection_task
from app.telemetry.service import length_bucket
from app.telemetry.tasks import record_intent_telemetry_task
from app.twin.models import Twin

logger = get_logger(__name__)


class ConversationNotFoundError(NotFoundError):
    code = "conversation_not_found"


class MessageInProgressError(ConflictError):
    """The same client request id is being processed by another request."""

    code = "message_in_progress"


# Listing bounds. A conversation list or a transcript is a screenful of rows;
# nothing legitimate needs an unbounded read.
CONVERSATION_LIST_DEFAULT = 100
CONVERSATION_LIST_MAX = 200
MESSAGE_LIST_DEFAULT = 200
MESSAGE_LIST_MAX = 500

# A conversation with no title shows as a row of identical placeholders, so
# the first message names it.
_AUTO_TITLE_CHARS = 60

# User turn before twin turn when two rows share a timestamp.
_ROLE_ORDER = case((Message.role == "user", 0), else_=1)


class ConversationService:
    # Sprint 4 (DF8): a hard cap on the number of active goals carried into
    # the prompt per turn. Kept as a service-layer constant so the
    # ContextBuilder's `max_active_goals` and the goal query stay aligned.
    _MAX_ACTIVE_GOALS_IN_CONTEXT: int = 3

    def __init__(
        self,
        session: AsyncSession,
        provider: LLMProvider | None,
        *,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        llm_model: str | None = None,
        task_runner: TaskRunner | None = None,
        extraction_provider: LLMProvider | None = None,
        retriever: MemoryRetriever | None = None,
        context_builder: ContextBuilder | None = None,
        goal_service: GoalService | None = None,
        intent_detector: IntentDetector | None = None,
        settings: Settings | None = None,
        evolution_service: EvolutionService | None = None,
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
        # Sprint 8: settings pass-through so the scheduled reflection
        # task can read opportunity thresholds. Nullable — tests that
        # construct the service directly without a settings instance
        # keep working; the scheduler is only enqueued when settings
        # AND sessionmaker AND task_runner are all wired.
        self._settings = settings
        # Sprint 10: owner-scoped reader/cursor-advancer for
        # twin_evolution_events. Nullable so unit tests that construct
        # ConversationService without it keep working; the chat-time
        # learning acknowledgement is a no-op when not wired.
        self._evolution_service = evolution_service

    async def list_for_twin(
        self,
        twin: Twin,
        *,
        limit: int = CONVERSATION_LIST_DEFAULT,
        offset: int = 0,
    ) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.twin_id == twin.id)
            .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
            .limit(max(1, min(limit, CONVERSATION_LIST_MAX)))
            .offset(max(0, offset))
        )
        return list((await self._session.execute(stmt)).scalars())

    async def get(self, twin: Twin, conversation_id: uuid.UUID) -> Conversation:
        """The conversation row, owner-scoped. Messages are NOT loaded: every
        caller that wants them asks for a bounded slice."""
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.twin_id == twin.id,
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

    async def list_messages(
        self,
        twin: Twin,
        conversation_id: uuid.UUID,
        *,
        limit: int = MESSAGE_LIST_DEFAULT,
        before: uuid.UUID | None = None,
    ) -> list[Message]:
        """The most recent `limit` messages, oldest first.

        `before` is a message id from a previous page; the result is the
        slice immediately older than it.
        """
        conv = await self.get(twin, conversation_id)
        return await self._recent_messages(
            conv.id,
            limit=max(1, min(limit, MESSAGE_LIST_MAX)),
            before=before,
        )

    async def _recent_messages(
        self,
        conversation_id: uuid.UUID,
        *,
        limit: int,
        before: uuid.UUID | None = None,
        exclude: uuid.UUID | None = None,
    ) -> list[Message]:
        stmt = select(Message).where(Message.conversation_id == conversation_id)
        if before is not None:
            cursor = (
                select(Message.created_at)
                .where(Message.id == before, Message.conversation_id == conversation_id)
                .scalar_subquery()
            )
            stmt = stmt.where(Message.created_at < cursor)
        if exclude is not None:
            stmt = stmt.where(Message.id != exclude)
        stmt = stmt.order_by(Message.created_at.desc(), _ROLE_ORDER.desc()).limit(limit)
        rows = list((await self._session.execute(stmt)).scalars())
        rows.reverse()
        return rows

    async def _find_exchange(
        self, conversation_id: uuid.UUID, client_request_id: str
    ) -> tuple[Message, Message] | None:
        """The stored (user, twin) pair for a client request id, if any."""
        user_msg = (
            await self._session.execute(
                select(Message).where(
                    Message.conversation_id == conversation_id,
                    Message.client_request_id == client_request_id,
                )
            )
        ).scalar_one_or_none()
        if user_msg is None:
            return None
        reply_id = (user_msg.metadata_json or {}).get("reply_message_id")
        if reply_id is None:
            return None
        twin_msg = (
            await self._session.execute(
                select(Message).where(
                    Message.id == uuid.UUID(str(reply_id)),
                    Message.conversation_id == conversation_id,
                )
            )
        ).scalar_one_or_none()
        if twin_msg is None:
            return None
        return user_msg, twin_msg

    async def _insert_user_message(
        self,
        conv: Conversation,
        user_msg: Message,
        client_request_id: str | None,
    ) -> tuple[Message, Message] | None:
        """Write the user turn. Returns a stored exchange instead when another
        request already owns this client request id.

        The insert runs inside a SAVEPOINT so losing the uniqueness race
        rolls back only the insert and leaves the request's transaction (and
        everything already loaded in it) usable.
        """
        try:
            async with self._session.begin_nested():
                if client_request_id is not None and self._is_postgres():
                    # A concurrent request holding the same key keeps its row
                    # uncommitted until its model call returns. Waiting that
                    # long would pin this connection for no benefit.
                    await self._session.execute(text("SET LOCAL lock_timeout = '3s'"))
                self._session.add(user_msg)
                await self._session.flush()
        except IntegrityError:
            if client_request_id is None:
                raise
            existing = await self._find_exchange(conv.id, client_request_id)
            if existing is None:
                raise MessageInProgressError(
                    "This message is still being processed. Please wait a moment.",
                    headers={"Retry-After": "3"},
                ) from None
            return existing
        except DBAPIError as exc:
            if client_request_id is not None and _is_lock_timeout(exc):
                raise MessageInProgressError(
                    "This message is still being processed. Please wait a moment.",
                    headers={"Retry-After": "3"},
                ) from None
            raise
        return None

    def _is_postgres(self) -> bool:
        bind = self._session.bind
        return bind is not None and bind.dialect.name == "postgresql"

    async def post_message(
        self,
        twin: Twin,
        conversation_id: uuid.UUID,
        content: str,
        *,
        client_request_id: str | None = None,
    ) -> tuple[Message, Message, bool]:
        """Persist the user turn, retrieve relevant memory, run the pipeline,
        persist the twin turn, enqueue extraction.

        Returns `(user_message, twin_message, replayed)`. `replayed` is True
        when the pair was already stored for this `client_request_id` and no
        model call was made.

        Retrieval and extraction are both best-effort. A failing retriever
        yields an empty-memory context (chat still works). A failing
        extractor is handled in the background task.

        Hard precondition: an LLM provider must be configured. The dep
        wires `None` through when no provider is usable (so GET
        /conversations keeps working without a key); here we refuse the
        request BEFORE any DB write so a key-less POST cannot leave an
        orphan user message that the twin never replies to. The 503
        envelope matches what `app.llm.registry.ProviderNotConfiguredError`
        would have produced from the dep, so clients see one shape either
        way.

        All-or-nothing: the user turn and the twin turn commit together. If
        the model call fails nothing is stored, the client still holds the
        draft, and a retry cannot double a message.

        `client_request_id` makes the call idempotent. A repeat of a request
        that already completed returns the stored exchange without calling
        the model again; a repeat that arrives while the first is still
        running is refused with 409 `message_in_progress`.
        """
        if self._provider is None:
            raise ProviderNotConfiguredError(
                "No usable LLM provider is configured; set ANTHROPIC_API_KEY "
                "(or configure another provider) before posting chat messages."
            )

        conv = await self.get(twin, conversation_id)

        if client_request_id is not None:
            stored = await self._find_exchange(conv.id, client_request_id)
            if stored is not None:
                return stored[0], stored[1], True

        # Sprint 6: intent detection and context policy FIRST. The
        # resolved policy drives the retriever's `limit`, the goal
        # service's `limit`, and the ContextBuilder's budget — so a
        # casual TALK pulls fewer memories than a deep REFLECT, without
        # any downstream code learning about intents.
        intent_t0 = time.perf_counter()
        intent_result = await self._detect_intent_safely(
            user_message=content,
            conversation_id=conv.id,
            twin=twin,
        )
        intent_latency_ms = int((time.perf_counter() - intent_t0) * 1000)
        policy = self._policy_for_intent_safely(
            intent_result=intent_result,
            conversation_id=conv.id,
            twin=twin,
        )
        twin_state = TwinState(intent_result=intent_result, policy=policy)

        # Only the window the prompt will actually use is read. Loading the
        # whole transcript made every turn cost in proportion to the length
        # of the conversation.
        history = await self._recent_messages(
            conv.id,
            limit=max(policy.context_budget().max_history_turns, 1) + 4,
        )

        # Timestamps within a conversation are strictly increasing, so the
        # transcript has one unambiguous order even when two turns land
        # inside the clock's resolution.
        user_created_at = _after(history[-1].created_at if history else None)
        twin_message_id = new_id()
        user_msg = Message(
            conversation_id=conv.id,
            role="user",
            content=content,
            created_at=user_created_at,
            client_request_id=client_request_id,
            # Lets a replay find the reply without guessing from timestamps.
            metadata_json=(
                {"reply_message_id": str(twin_message_id)} if client_request_id is not None else {}
            ),
        )
        stored = await self._insert_user_message(conv, user_msg, client_request_id)
        if stored is not None:
            return stored[0], stored[1], True

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

        # Sprint 10: chat-time learning acknowledgement. Surfaces
        # confirmed Twin-evolution events the user has not seen yet and
        # advances the twin's acknowledgement cursor — both inside the
        # SAME transaction that persists the twin message below, so the
        # chip the user sees and the cursor advance commit atomically.
        # Never raises into the chat path.
        learning = await self._acknowledge_learning_safely(
            twin=twin,
            conversation_id=conv.id,
        )

        twin_msg = Message(
            id=twin_message_id,
            conversation_id=conv.id,
            role="twin",
            content=response.content,
            created_at=_after(user_created_at),
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
                # Sprint 10: null when nothing new to acknowledge or the
                # ack path is not wired. The mobile client reads this via
                # the generic metadata_json passthrough.
                "learning": learning,
            },
        )
        self._session.add(twin_msg)
        # The list is ordered by last activity, and an untitled conversation
        # is named after the message that opened it.
        conv.updated_at = twin_msg.created_at
        if not conv.title:
            conv.title = _auto_title(content)
        # Commit and stop. Both rows were built here with every column set,
        # and the session keeps their state across the commit, so there is
        # nothing to re-read. Re-reading them used to open a new transaction
        # that stayed open, pinning this request's connection for as long as
        # the background work below (which makes model calls of its own)
        # took to finish.
        await self._session.commit()

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
            learning_surfaced=(learning["count"] if learning else 0),
        )

        self._enqueue_memory_extraction(
            twin=twin,
            conversation_id=conv.id,
            user_message_id=user_msg.id,
            twin_message_id=twin_msg.id,
        )
        # Sprint 8: intent telemetry — SAFE-METADATA-ONLY row. The
        # length bucket is computed HERE so the task coroutine never
        # sees the raw user message.
        self._enqueue_intent_telemetry(
            twin=twin,
            user_message=content,
            intent_result=intent_result,
            intent_latency_ms=intent_latency_ms,
        )
        # Sprint 8: reflection scheduler. Runs AFTER the chat response
        # has been persisted. Policy almost always returns SKIP; even
        # when it runs, exceptions are swallowed so chat is unaffected.
        self._enqueue_reflection_scheduler(twin=twin)

        return user_msg, twin_msg, False

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

    async def _acknowledge_learning_safely(
        self,
        *,
        twin: Twin,
        conversation_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        """Surface unacknowledged Twin-evolution events and advance the cursor.

        Returns a `learning` metadata block (or `None` when there is
        nothing to surface, the ack reader is not wired, or the lookup
        failed). The cursor advance (`twin.last_acknowledged_evolution_seq`)
        is left pending on the session so it flushes with the twin-message
        insert at `post_message`'s single commit — the chip and the cursor
        move atomically.

        Lock / isolation shape (Sprint 10, Corrections 6/9/12/13):

        - The per-twin evolution advisory lock is acquired inside a
          SAVEPOINT and the SAVEPOINT is RELEASED on success, which
          promotes the (transaction-level) lock to the outer chat
          transaction — so it is held through the cursor advance and
          commit, serializing concurrent chats for the same twin and
          preventing a double-surface. On any failure the SAVEPOINT is
          rolled back (releasing the lock and undoing the read) and the
          outer chat transaction stays usable, so the twin message still
          persists. The ack never fails the chat.
        - On Postgres a short `lock_timeout` bounds the wait so a chat
          never hangs on a concurrent holder (or a migration's ACCESS
          EXCLUSIVE); on timeout the turn simply carries no chip and the
          next turn surfaces the backlog. No-op on SQLite.
        """
        if self._evolution_service is None:
            return None
        events: list[Any] = []
        try:
            async with self._session.begin_nested():
                if self._session.bind is not None and (
                    self._session.bind.dialect.name == "postgresql"
                ):
                    await self._session.execute(text("SET LOCAL lock_timeout = '2s'"))
                await acquire_twin_evolution_lock(self._session, twin.id)
                # Defeat stale ORM state: the twin was loaded (and its
                # cursor read) BEFORE we held the advisory lock, so a
                # concurrent chat that advanced the cursor and committed
                # while we waited for the lock would otherwise be invisible
                # to us — and we would re-surface the same events (a
                # double-surface). Re-read the cursor now that we hold the
                # lock, under READ COMMITTED, so the surface query filters
                # on the current committed high-water mark.
                await self._session.refresh(
                    twin, attribute_names=["last_acknowledged_evolution_seq"]
                )
                events = list(
                    await self._evolution_service.unacknowledged_for_twin(
                        twin, limit=ACK_SURFACE_LIMIT
                    )
                )
        except Exception as exc:
            logger.warning(
                "conversation.learning_ack.lookup_failed",
                conversation_id=str(conversation_id),
                twin_id=str(twin.id),
                error=type(exc).__name__,
            )
            return None

        learning = compose_learning(events)
        if learning is None:
            return None
        # Advance the cursor in the OUTER transaction so it commits with
        # the twin message. Never moves backward.
        twin.last_acknowledged_evolution_seq = int(learning["acknowledged_up_to_seq"])
        logger.info(
            "conversation.learning_ack.surfaced",
            conversation_id=str(conversation_id),
            twin_id=str(twin.id),
            count=learning["count"],
            up_to_seq=learning["acknowledged_up_to_seq"],
        )
        return learning

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

    def _enqueue_intent_telemetry(
        self,
        *,
        twin: Twin,
        user_message: str,
        intent_result: IntentResult,
        intent_latency_ms: int,
    ) -> None:
        """Sprint 8: enqueue a telemetry row for the detected intent.

        The length bucket is computed HERE so the raw user message is
        NOT passed to the task coroutine. The task writes only
        safe-metadata fields. Failure is isolated.
        """
        if self._task_runner is None or self._sessionmaker is None:
            return
        bucket = length_bucket(user_message)
        detector_name = getattr(self._intent_detector, "detector_name", "unknown")
        self._task_runner.enqueue(
            record_intent_telemetry_task,
            sessionmaker=self._sessionmaker,
            user_id=twin.user_id,
            twin_id=twin.id,
            intent=intent_result.intent.value,
            confidence=float(intent_result.confidence),
            reason=intent_result.reason,
            detector_name=detector_name,
            latency_ms=intent_latency_ms,
            message_length_bucket=bucket,
        )

    def _enqueue_reflection_scheduler(self, *, twin: Twin) -> None:
        """Sprint 8: enqueue the reflection scheduler for this twin.

        No-op when the service is not wired for background work (unit
        tests that construct ConversationService without a runner).
        """
        if (
            self._task_runner is None
            or self._sessionmaker is None
            or self._llm_model is None
            or self._settings is None
        ):
            return
        self._task_runner.enqueue(
            scheduled_reflection_task,
            sessionmaker=self._sessionmaker,
            llm_provider=self._provider,
            llm_model=self._llm_model,
            user_id=twin.user_id,
            twin_id=twin.id,
            settings=self._settings,
        )


def _after(previous: datetime | None) -> datetime:
    """Now, but never at or before `previous`."""
    now = utcnow()
    if previous is None:
        return now
    if previous.tzinfo is None:
        # SQLite hands timestamps back without their zone; they are UTC.
        previous = previous.replace(tzinfo=UTC)
    return max(now, previous + timedelta(microseconds=1))


def _auto_title(content: str) -> str:
    first_line = content.strip().splitlines()[0].strip() if content.strip() else ""
    if len(first_line) <= _AUTO_TITLE_CHARS:
        return first_line
    return first_line[: _AUTO_TITLE_CHARS - 1].rstrip() + "…"


def _is_lock_timeout(exc: DBAPIError) -> bool:
    """True for Postgres `lock_not_available` (SQLSTATE 55P03)."""
    orig = exc.orig
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return code == "55P03"
