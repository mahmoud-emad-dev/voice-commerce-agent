from __future__ import annotations

import logging
from typing import Any

import structlog

from voice_commerce.config.settings import settings


def build_structlog_processors(*, log_json: bool) -> list[Any]:
    """Build the shared structlog processor chain for console or JSON output."""
    renderer = (
        structlog.processors.JSONRenderer()
        if log_json
        else structlog.dev.ConsoleRenderer()
    )
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        renderer,
    ]


def configure_logging() -> None:
    """Configure structlog and stdlib logging once for the current app settings."""
    log_level = getattr(logging, settings.log_level, logging.INFO)
    processors = build_structlog_processors(log_json=settings.should_log_json)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        filename=settings.log_file_path or None,
        force=True,
    )
