"""Errors an LLM provider can surface to the API layer.

Each one carries a stable `code` the client can branch on and a message that
is safe to show a user. Provider-specific detail (their error text, request
ids) is logged by the provider and never placed in the message.
"""

from __future__ import annotations

from app.common.errors import APIError


class LLMProviderError(APIError):
    """The provider answered, but not with something usable."""

    status_code = 502
    code = "llm_provider_error"


class LLMMisconfiguredError(APIError):
    """The provider rejected our credentials or our model id.

    An operator problem, not a user problem and not a transient one: retrying
    will not help until configuration changes.
    """

    status_code = 503
    code = "llm_provider_misconfigured"


class LLMRateLimitedError(APIError):
    status_code = 429
    code = "llm_rate_limited"


class LLMTimeoutError(APIError):
    status_code = 504
    code = "llm_timeout"


class LLMUnavailableError(APIError):
    """Overloaded, unreachable, or failing on the provider's side."""

    status_code = 503
    code = "llm_unavailable"


class LLMRefusedError(APIError):
    """The model declined to answer this message."""

    status_code = 422
    code = "llm_refused"
