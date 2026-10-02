"""Structured logging via structlog.

Message content (chat text) MUST NEVER be logged. Log memory IDs, similarity
scores, provider names, latencies, and token counts — never the words the
user typed or the words the twin replied with.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, cast

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Idempotent structlog setup. Safe to call more than once."""

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.EventRenamer("event"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None, **initial: Any) -> structlog.stdlib.BoundLogger:
    logger = structlog.get_logger(name)
    if initial:
        logger = logger.bind(**initial)
    return cast("structlog.stdlib.BoundLogger", logger)
