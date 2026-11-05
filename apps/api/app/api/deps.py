"""FastAPI dependencies.

All request-scoped dependencies live here. Tests override them by name
against `app.dependency_overrides`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import BackgroundTasks, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import AuthenticatedUser
from app.auth.supabase import verify_supabase_jwt
from app.common.errors import UnauthorizedError
from app.common.tasks import FastAPIBackgroundRunner, TaskRunner
from app.config import Settings, get_settings
from app.conversation.intent import DEFAULT_INTENT_DETECTOR, IntentDetector
from app.conversation.service import ConversationService
from app.db.session import get_db_session, get_sessionmaker
from app.goal.service import GoalService
from app.llm.interface import EmbeddingProvider, LLMProvider
from app.llm.registry import (
    ProviderNotConfiguredError,
    get_embedding_provider,
    get_llm_provider,
)
from app.memory.context import ContextBuilder
from app.memory.retrieval import MemoryRetriever
from app.memory.service import MemoryService
from app.twin.service import TwinService


async def db_session_dep() -> AsyncIterator[AsyncSession]:
    async for s in get_db_session():
        yield s


def sessionmaker_dep() -> async_sessionmaker[AsyncSession]:
    return get_sessionmaker()


DBSession = Annotated[AsyncSession, Depends(db_session_dep)]
SessionmakerDep = Annotated[async_sessionmaker[AsyncSession], Depends(sessionmaker_dep)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
LLMProviderDep = Annotated[LLMProvider, Depends(get_llm_provider)]
EmbeddingProviderDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]


def extraction_llm_provider_dep(
    chat_provider: LLMProviderDep,
) -> LLMProvider:
    """The LLM provider used for memory extraction.

    By default returns the same provider as chat, so a single `LLM_PROVIDER`
    setting powers both. Declared as its own FastAPI dependency so tests —
    and, later, a Sprint 3+ `EXTRACTION_LLM_PROVIDER` config — can override
    the extraction path WITHOUT affecting chat. This is the mechanism that
    guarantees `test_extraction_failure_does_not_fail_chat`.
    """
    return chat_provider


ExtractionLLMProviderDep = Annotated[LLMProvider, Depends(extraction_llm_provider_dep)]


# ---------------------------------------------------------------------
# Optional LLM dependencies for mixed routers (non-AI + AI endpoints
# sharing one service).
#
# The conversations router carries four pure-DB routes (create, list,
# retrieve, list-messages) alongside the one route that actually needs
# the LLM (post_message). Declaring `ConversationServiceDep` with hard
# `LLMProviderDep`/`ExtractionLLMProviderDep` dependencies meant every
# one of those routes resolved the LLM provider up front — so a missing
# `ANTHROPIC_API_KEY` returned 503 for every /v1/conversations* call,
# including the GETs that never touch the LLM. The optional variants
# below defer the 503 to the handler that actually needs the provider
# (see `ConversationService.post_message`), which checks for `None` and
# raises `ProviderNotConfiguredError` itself.
#
# These catch ONLY `ProviderNotConfiguredError` on purpose: any OTHER
# exception from provider construction (a broken SDK, a settings bug,
# an unknown provider name) is still a 500 the operator needs to see,
# not something to be silently downgraded to a degraded request path.
# ---------------------------------------------------------------------


def optional_llm_provider_dep(request: Request) -> LLMProvider | None:
    """Same provider lookup as the hard LLMProviderDep, but a missing
    key returns None instead of raising 503.

    Routes through `app.dependency_overrides` by hand so a test that
    overrides `get_llm_provider` to inject a fake provider still wins
    here — the override map is FastAPI's own, which Depends() normally
    consults for us, but the try/except has to live in Python code, so
    the lookup is explicit.
    """
    resolver = request.app.dependency_overrides.get(get_llm_provider, get_llm_provider)
    try:
        provider: LLMProvider = resolver()
    except ProviderNotConfiguredError:
        return None
    return provider


OptionalLLMProviderDep = Annotated[LLMProvider | None, Depends(optional_llm_provider_dep)]


def optional_extraction_llm_provider_dep(
    request: Request,
    chat_provider: OptionalLLMProviderDep,
) -> LLMProvider | None:
    """Extraction provider mirrors chat by default; nullable here too.

    Honours an override of `extraction_llm_provider_dep` (e.g. a test
    injecting a deliberately broken extraction provider while chat
    stays healthy) by routing through the override map the same way
    the chat lookup does. If no override is set, falls back to the
    chat provider, matching the real signature.
    """
    override = request.app.dependency_overrides.get(extraction_llm_provider_dep)
    if override is None:
        return chat_provider
    try:
        provider: LLMProvider = override()
    except ProviderNotConfiguredError:
        return None
    return provider


OptionalExtractionLLMProviderDep = Annotated[
    LLMProvider | None, Depends(optional_extraction_llm_provider_dep)
]


def task_runner_dep(background_tasks: BackgroundTasks) -> TaskRunner:
    return FastAPIBackgroundRunner(background_tasks)


TaskRunnerDep = Annotated[TaskRunner, Depends(task_runner_dep)]


async def get_current_user(
    settings: SettingsDep,
    authorization: str | None = Header(default=None),
) -> AuthenticatedUser:
    if not authorization:
        raise UnauthorizedError("Missing Authorization header.")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise UnauthorizedError("Authorization header must be 'Bearer <token>'.")
    return verify_supabase_jwt(parts[1], settings)


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


def twin_service_dep(session: DBSession) -> TwinService:
    return TwinService(session)


TwinServiceDep = Annotated[TwinService, Depends(twin_service_dep)]


def evolution_service_dep(session: DBSession) -> EvolutionService:
    from app.evolution.service import EvolutionService

    return EvolutionService(session)


EvolutionServiceDep = Annotated["EvolutionService", Depends(evolution_service_dep)]


def memory_service_dep(
    session: DBSession,
    embedding_provider: EmbeddingProviderDep,
    evolution: EvolutionServiceDep,
) -> MemoryService:
    # Sprint 8: pass the evolution writer so a confirmed memory
    # candidate emits a `memory_learned` event inside the SAME
    # transaction as the memory + source rows.
    return MemoryService(
        session,
        embedding_provider=embedding_provider,
        evolution_service=evolution,
    )


MemoryServiceDep = Annotated[MemoryService, Depends(memory_service_dep)]


def memory_retriever_dep(
    session: DBSession,
    embedding_provider: EmbeddingProviderDep,
) -> MemoryRetriever:
    return MemoryRetriever(session, embedding_provider=embedding_provider)


MemoryRetrieverDep = Annotated[MemoryRetriever, Depends(memory_retriever_dep)]


def context_builder_dep() -> ContextBuilder:
    return ContextBuilder()


ContextBuilderDep = Annotated[ContextBuilder, Depends(context_builder_dep)]


def goal_service_dep(session: DBSession) -> GoalService:
    return GoalService(session)


GoalServiceDep = Annotated[GoalService, Depends(goal_service_dep)]


def intent_detector_dep() -> IntentDetector:
    """Sprint 6: the request-scoped `IntentDetector`.

    Returns the deterministic rule-based detector by default. Tests
    override this dependency to inject stub detectors (e.g. an
    always-fails detector exercising the Sprint-6 failure-isolation
    branch, or a canned-result detector pinning a specific intent).
    """
    return DEFAULT_INTENT_DETECTOR


IntentDetectorDep = Annotated[IntentDetector, Depends(intent_detector_dep)]


def conversation_service_dep(
    session: DBSession,
    provider: OptionalLLMProviderDep,
    extraction_provider: OptionalExtractionLLMProviderDep,
    sessionmaker: SessionmakerDep,
    task_runner: TaskRunnerDep,
    settings: SettingsDep,
    retriever: MemoryRetrieverDep,
    context_builder: ContextBuilderDep,
    goal_service: GoalServiceDep,
    intent_detector: IntentDetectorDep,
    evolution: EvolutionServiceDep,
) -> ConversationService:
    return ConversationService(
        session,
        provider,
        sessionmaker=sessionmaker,
        llm_model=settings.llm_model,
        task_runner=task_runner,
        extraction_provider=extraction_provider,
        retriever=retriever,
        context_builder=context_builder,
        goal_service=goal_service,
        intent_detector=intent_detector,
        settings=settings,
        evolution_service=evolution,
    )


ConversationServiceDep = Annotated[ConversationService, Depends(conversation_service_dep)]


# ---------------------------------------------------------------------
# Sprint 7: reflection dependencies
# ---------------------------------------------------------------------


def reflection_service_dep(session: DBSession) -> ReflectionService:
    from app.reflection.service import ReflectionService

    return ReflectionService(session)


def reflection_extractor_dep(
    provider: LLMProviderDep,
    settings: SettingsDep,
) -> ReflectionExtractor:
    """The reflection extractor shares the chat `LLMProvider` by default.

    Tests override this dependency to pin a canned extractor or an
    exploding one. A later `REFLECTION_LLM_PROVIDER` config can be
    added here without touching callers (same shape as
    `extraction_llm_provider_dep`).
    """
    from app.reflection.extractor import ReflectionExtractor

    return ReflectionExtractor(provider, settings.llm_model)


ReflectionServiceDep = Annotated["ReflectionService", Depends(reflection_service_dep)]
ReflectionExtractorDep = Annotated["ReflectionExtractor", Depends(reflection_extractor_dep)]


# Imports kept at the bottom so the forward-referenced Annotated types
# resolve at import time without introducing a cycle.
from app.evolution.service import EvolutionService  # noqa: E402, F401
from app.reflection.extractor import ReflectionExtractor  # noqa: E402, F401
from app.reflection.service import ReflectionService  # noqa: E402, F401
