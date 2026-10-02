"""Smallest clean abstraction for background work.

Sprint 2 runs background work via FastAPI's built-in `BackgroundTasks`,
which executes after the response is sent but before the ASGI call
completes. `httpx.AsyncClient` + `ASGITransport` waits for completion, so
tests observe side effects after `await client.post(...)` returns.

Future sprints that need cross-process durability (Redis + arq) swap
`FastAPIBackgroundRunner` for an `ArqRunner` without touching callers.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, ClassVar, Protocol, runtime_checkable

from fastapi import BackgroundTasks

TaskFn = Callable[..., Any]


@runtime_checkable
class TaskRunner(Protocol):
    runner_name: ClassVar[str]

    def enqueue(self, func: TaskFn, /, *args: Any, **kwargs: Any) -> None: ...


class FastAPIBackgroundRunner(TaskRunner):
    """Production path: hands off to FastAPI's `BackgroundTasks`."""

    runner_name: ClassVar[str] = "fastapi"

    def __init__(self, background_tasks: BackgroundTasks) -> None:
        self._bg = background_tasks

    def enqueue(self, func: TaskFn, /, *args: Any, **kwargs: Any) -> None:
        self._bg.add_task(func, *args, **kwargs)


class ImmediateRunner(TaskRunner):
    """Test path: records enqueued tasks, drained on demand.

    Used by the test suite to make background-task assertions deterministic
    without relying on httpx's lifecycle for correctness.
    """

    runner_name: ClassVar[str] = "immediate"

    def __init__(self) -> None:
        self._pending: list[tuple[TaskFn, tuple[Any, ...], dict[str, Any]]] = []

    def enqueue(self, func: TaskFn, /, *args: Any, **kwargs: Any) -> None:
        self._pending.append((func, args, kwargs))

    async def drain(self) -> None:
        """Run every enqueued task to completion, in order."""
        while self._pending:
            func, args, kwargs = self._pending.pop(0)
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                await result

    def pending_count(self) -> int:
        return len(self._pending)
