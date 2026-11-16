"""Composite v1 router."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import rate_limit
from app.api.v1 import (
    conversations,
    evolution,
    goals,
    health,
    memories,
    reflections,
    twin,
)

# Every authenticated route shares one per-user budget. Routes that call a
# model add a tighter one of their own on top.
_authenticated = [Depends(rate_limit("default"))]

v1_router = APIRouter()
v1_router.include_router(health.router, tags=["system"])
v1_router.include_router(twin.router, prefix="/twin", tags=["twin"], dependencies=_authenticated)
v1_router.include_router(
    evolution.router,
    prefix="/twin/evolution",
    tags=["twin-evolution"],
    dependencies=_authenticated,
)
v1_router.include_router(
    conversations.router,
    prefix="/conversations",
    tags=["conversations"],
    dependencies=_authenticated,
)
v1_router.include_router(
    memories.memories_router,
    prefix="/memories",
    tags=["memories"],
    dependencies=_authenticated,
)
v1_router.include_router(
    memories.candidates_router,
    prefix="/memory-candidates",
    tags=["memory-candidates"],
    dependencies=_authenticated,
)
v1_router.include_router(goals.router, prefix="/goals", tags=["goals"], dependencies=_authenticated)
v1_router.include_router(
    reflections.router,
    prefix="/reflections",
    tags=["reflections"],
    dependencies=_authenticated,
)
