"""Structured logging setup (structlog + stdlib logging bridge)."""

from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import get_settings

_configured = False


def setup_logging() -> None:
    """Configure structlog once for the process.

    Dev renders a coloured console; non-dev emits JSON lines for log shippers.
    """
    global _configured
    if _configured:
        return

    settings = get_settings()

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.typing.Processor = (
        structlog.dev.ConsoleRenderer()
        if settings.is_dev
        else structlog.processors.JSONRenderer()
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger (configuring logging on first use)."""
    if not _configured:
        setup_logging()
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
