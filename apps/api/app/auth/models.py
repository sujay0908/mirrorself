"""Authentication value objects.

`AuthenticatedUser` is the request-scoped identity, resolved from a Supabase
JWT. It is deliberately minimal: the FastAPI service never trusts
client-supplied identity.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    supabase_id: uuid.UUID
    email: str | None = None

    @property
    def user_id(self) -> uuid.UUID:
        # In Sprint 1 the Supabase user id IS the user_id used to scope Twins.
        # If we later introduce a local `users` table this indirection lets us
        # swap the mapping in one place.
        return self.supabase_id
