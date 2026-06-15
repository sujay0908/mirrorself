"""
Redis connection pool and helper utilities.
"""
import json
from typing import Any, Optional

import redis.asyncio as redis_async

from app.core.config import settings
from app.core.logging import logger


class RedisClient:
    """Async Redis wrapper used for memory + caching."""

    def __init__(self) -> None:
        self.pool = redis_async.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=50,
        )
        self._client: Optional[redis_async.Redis] = None

    @property
    def client(self) -> redis_async.Redis:
        if self._client is None:
            self._client = redis_async.Redis(connection_pool=self.pool)
        return self._client

    async def get(self, key: str) -> Optional[str]:
        try:
            return await self.client.get(key)
        except Exception as e:
            logger.error(f"Redis GET failed for {key}: {e}")
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        try:
            if not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False, default=str)
            return bool(await self.client.set(key, value, ex=ttl))
        except Exception as e:
            logger.error(f"Redis SET failed for {key}: {e}")
            return False

    async def delete(self, *keys: str) -> int:
        try:
            return await self.client.delete(*keys)
        except Exception as e:
            logger.error(f"Redis DELETE failed for {keys}: {e}")
            return 0

    async def lpush(self, key: str, *values: Any) -> int:
        try:
            payload = [
                v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
                for v in values
            ]
            return await self.client.lpush(key, *payload)
        except Exception as e:
            logger.error(f"Redis LPUSH failed for {key}: {e}")
            return 0

    async def lrange(self, key: str, start: int = 0, end: int = -1) -> list[str]:
        try:
            result = await self.client.lrange(key, start, end)
            return result or []
        except Exception as e:
            logger.error(f"Redis LRANGE failed for {key}: {e}")
            return []

    async def keys(self, pattern: str) -> list[str]:
        try:
            return await self.client.keys(pattern)
        except Exception as e:
            logger.error(f"Redis KEYS failed for {pattern}: {e}")
            return []

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        await self.pool.disconnect()


redis_client = RedisClient()
