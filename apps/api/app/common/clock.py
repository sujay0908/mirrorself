"""The clock rows are stamped with.

Lists throughout the API are ordered by a timestamp ("newest first",
"chronological"). Two rows written inside one tick of the system clock get
the same timestamp, and their relative order then falls to whatever breaks
the tie, which for random UUID keys is nothing meaningful. Clock resolution
is about a microsecond on Linux but 15 milliseconds on Windows, where this
showed up as tests that failed one run in several.

`utcnow()` never returns the same instant twice in one process and never
goes backwards, so rows stamped by it have exactly one order. The cost is
that a burst of writes is stamped a few microseconds ahead of the wall clock.

The guarantee is per process. It holds for the API as deployed (one
instance); across several instances, two requests could still tie, which is
why anything that must be totally ordered across writers (evolution events)
carries its own database sequence instead of relying on this.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

_lock = threading.Lock()
_last = datetime.min.replace(tzinfo=UTC)
_TICK = timedelta(microseconds=1)


def utcnow() -> datetime:
    """Current UTC time, strictly later than any value returned before."""
    global _last
    with _lock:
        now = datetime.now(tz=UTC)
        if now <= _last:
            now = _last + _TICK
        _last = now
        return now
