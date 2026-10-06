"""Composite v1 router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import conversations, goals, health, memories, reflections, twin

v1_router = APIRouter()
v1_router.include_router(health.router, tags=["system"])
v1_router.include_router(twin.router, prefix="/twin", tags=["twin"])
v1_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
v1_router.include_router(memories.memories_router, prefix="/memories", tags=["memories"])
v1_router.include_router(
    memories.candidates_router,
    prefix="/memory-candidates",
    tags=["memory-candidates"],
)
v1_router.include_router(goals.router, prefix="/goals", tags=["goals"])
v1_router.include_router(reflections.router, prefix="/reflections", tags=["reflections"])
