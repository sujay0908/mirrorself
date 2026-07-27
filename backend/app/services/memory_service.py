"""
Memory service. Two-tier:
  - Redis: rolling list of recent facts and short-term chat context (fast, ephemeral).
  - Postgres: durable `facts` table for long-term recall.

A new fact is added if it doesn't closely duplicate an existing one (Jaccard
over word tokens) and the assistant's LLM extraction flags it as durable.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import redis_client
from app.models.fact import Fact
from app.models.user import User


_TOKEN_RE = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class MemoryService:
    """Reads/writes user memory across Redis and Postgres."""

    def __init__(self) -> None:
        self.similarity_threshold = 0.7

    # ---------- Redis fast path ----------

    def _facts_key(self, user_id: int) -> str:
        return f"mirrorself:user:{user_id}:facts"

    def _short_term_key(self, user_id: int) -> str:
        return f"mirrorself:user:{user_id}:short_term"

    async def cache_fact(self, user_id: int, fact: dict) -> None:
        await redis_client.lpush(
            self._facts_key(user_id),
            {"category": fact.get("category"), "content": fact.get("content"), "ts": datetime.utcnow().isoformat()},
        )
        # Cap list length
        await redis_client.client.ltrim(self._facts_key(user_id), 0, 200)

    async def get_recent_facts(self, user_id: int, limit: int = 30) -> list[dict]:
        raw = await redis_client.lrange(self._facts_key(user_id), 0, limit - 1)
        out: list[dict] = []
        for r in raw:
            try:
                out.append(json.loads(r))
            except json.JSONDecodeError:
                continue
        return out

    async def push_short_term(self, user_id: int, role: str, content: str) -> None:
        await redis_client.lpush(
            self._short_term_key(user_id),
            {"role": role, "content": content, "ts": datetime.utcnow().isoformat()},
        )
        await redis_client.client.ltrim(self._short_term_key(user_id), 0, 40)

    async def get_short_term(self, user_id: int, limit: int = 20) -> list[dict]:
        raw = await redis_client.lrange(self._short_term_key(user_id), 0, limit - 1)
        out: list[dict] = []
        for r in raw:
            try:
                out.append(json.loads(r))
            except json.JSONDecodeError:
                continue
        return list(reversed(out))

    # ---------- Postgres durable path ----------

    async def is_duplicate(self, db: AsyncSession, user_id: int, content: str) -> bool:
        stmt = select(Fact).where(Fact.user_id == user_id).order_by(Fact.created_at.desc()).limit(100)
        result = await db.execute(stmt)
        existing = result.scalars().all()
        new_tokens = _tokens(content)
        for f in existing:
            if _jaccard(new_tokens, _tokens(f.content)) >= self.similarity_threshold:
                return True
        return False

    async def add_fact(
        self,
        db: AsyncSession,
        user_id: int,
        category: str,
        content: str,
        confidence: float = 0.7,
        source: Optional[str] = None,
    ) -> Optional[Fact]:
        if await self.is_duplicate(db, user_id, content):
            return None
        fact = Fact(
            user_id=user_id,
            category=category,
            content=content,
            confidence=confidence,
            source=source,
        )
        db.add(fact)
        await db.flush()
        await self.cache_fact(user_id, {"category": category, "content": content})
        return fact

    async def get_durable_facts(self, db: AsyncSession, user_id: int, limit: int = 50) -> list[Fact]:
        stmt = (
            select(Fact)
            .where(Fact.user_id == user_id)
            .order_by(Fact.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def merge(self, user: User, redis_facts: list[dict], db_facts: list[Fact]) -> list[dict]:
        """Combine both sources and dedupe by similarity for prompt injection."""
        merged: list[dict] = []
        seen_tokens: list[set[str]] = []
        for f in db_facts:
            t = _tokens(f.content)
            if any(_jaccard(t, s) >= self.similarity_threshold for s in seen_tokens):
                continue
            merged.append({"category": f.category, "content": f.content})
            seen_tokens.append(t)
        for f in redis_facts:
            content = f.get("content", "")
            t = _tokens(content)
            if not t:
                continue
            if any(_jaccard(t, s) >= self.similarity_threshold for s in seen_tokens):
                continue
            merged.append({"category": f.get("category", "fact"), "content": content})
            seen_tokens.append(t)
        return merged


memory_service = MemoryService()
