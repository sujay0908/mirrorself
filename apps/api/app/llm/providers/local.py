"""LocalProvider — stub for on-device or edge-hosted models.

Sprint 1 leaves this as a NotImplemented stub; its presence proves the
provider abstraction accommodates future local inference (survey Gap G3).
"""

from __future__ import annotations

from typing import ClassVar

from app.common.errors import APIError
from app.llm.interface import LLMProvider, LLMRequest, LLMResponse


class LocalProvider(LLMProvider):
    provider_name: ClassVar[str] = "local"

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        raise APIError(
            "LocalProvider is not implemented yet — planned for Sprint 5+.",
            code="not_implemented",
            status_code=501,
        )
