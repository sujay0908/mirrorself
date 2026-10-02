"""ID helpers.

Sprint 1 uses UUID4 (random). The API convention doc calls for UUIDv7
(time-ordered) — this is a Sprint 1.1 upgrade and is deliberately not blocking
the vertical slice. Callers use `new_id()` and never `uuid.uuid4()` directly,
so the switch is one-file when the library lands.
"""

from __future__ import annotations

import uuid


def new_id() -> uuid.UUID:
    return uuid.uuid4()
