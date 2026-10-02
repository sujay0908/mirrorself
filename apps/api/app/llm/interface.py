"""Provider-agnostic LLM interface.

**Rule (enforced by CI lint):** no module outside `app/llm/providers/` may
import a vendor SDK (`anthropic`, `openai`, ...). Domain code speaks only to
this interface.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

MessageRole = Literal["system", "user", "assistant"]


class LLMMessage(BaseModel):
    role: MessageRole
    content: str


class LLMRequest(BaseModel):
    messages: list[LLMMessage]
    model: str
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1, le=32768)
    stop_sequences: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    content: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """The single provider contract.

    Implementations live under `app/llm/providers/`. `provider_name` MUST be
    unique across providers — it is the value users set in `LLM_PROVIDER`.
    """

    provider_name: ClassVar[str]

    async def generate_response(self, request: LLMRequest) -> LLMResponse: ...


class EmbeddingRequest(BaseModel):
    texts: list[str]
    model: str


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    model: str
    provider: str
    dimensions: int


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Embedding-side sibling of `LLMProvider`.

    Sprint 1 does not persist embeddings; this interface is defined here so
    Sprint 2 can add a provider without disturbing domain code.
    """

    provider_name: ClassVar[str]

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...
