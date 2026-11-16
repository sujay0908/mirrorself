"""In-process token-bucket rate limiting.

State lives in this process's memory, which is correct while the API runs as
a single instance. Running more than one instance multiplies every limit by
the instance count; at that point the buckets have to move to a shared store
(Redis) behind this same interface.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

# A bucket untouched for this long has refilled completely, so dropping it
# changes nothing about the limit it enforces.
_IDLE_SECONDS = 120.0


class TokenBucketLimiter:
    """One bucket per key. Each allows `per_minute` requests as a burst and
    then refills at `per_minute / 60` tokens per second."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 50_000,
    ) -> None:
        self._clock = clock
        self._max_keys = max_keys
        # key -> (tokens remaining, time of last update)
        self._buckets: dict[str, tuple[float, float]] = {}

    def check(self, key: str, *, per_minute: int) -> float:
        """Spend one token for `key`.

        Returns 0.0 when the request is allowed, otherwise the number of
        seconds until a token is next available.
        """
        now = self._clock()
        capacity = float(per_minute)
        rate = capacity / 60.0
        tokens, last = self._buckets.get(key, (capacity, now))
        tokens = min(capacity, tokens + (now - last) * rate)
        if tokens >= 1.0:
            self._buckets[key] = (tokens - 1.0, now)
            if len(self._buckets) > self._max_keys:
                self._prune(now)
            return 0.0
        self._buckets[key] = (tokens, now)
        return (1.0 - tokens) / rate

    def _prune(self, now: float) -> None:
        self._buckets = {
            key: state for key, state in self._buckets.items() if now - state[1] < _IDLE_SECONDS
        }
        if len(self._buckets) > self._max_keys:
            # Still over: an attacker is minting keys faster than they idle
            # out. Keep the most recently active half.
            keep = sorted(self._buckets.items(), key=lambda item: item[1][1], reverse=True)
            self._buckets = dict(keep[: self._max_keys // 2])

    def reset(self) -> None:
        self._buckets.clear()

    def __len__(self) -> int:
        return len(self._buckets)


def retry_after_header(seconds: float) -> str:
    """Whole seconds, rounded up, never below 1."""
    return str(max(1, math.ceil(seconds)))


_limiter = TokenBucketLimiter()


def get_rate_limiter() -> TokenBucketLimiter:
    return _limiter
