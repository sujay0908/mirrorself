"""
Centralised logging configuration using loguru.
"""
import sys
from loguru import logger
from app.core.config import settings

# Remove default sink and configure
logger.remove()
logger.add(
    sys.stdout,
    level=settings.LOG_LEVEL,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    ),
    colorize=True,
)
logger.add(
    "logs/mirrorself_{time:YYYY-MM-DD}.log",
    level=settings.LOG_LEVEL,
    rotation="00:00",
    retention="30 days",
    compression="zip",
    enqueue=True,
)

__all__ = ["logger"]
