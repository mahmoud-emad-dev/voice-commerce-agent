from __future__ import annotations

import logging
from typing import Any

import structlog

from voice_commerce.config.settings import settings

_REDACTED = "[REDACTED]"
_SENSITIVE_FIELD_NAMES = {
    "admin_api_key",
    "api_key",
    "api_key_hash",
    "authorization",
    "cookie",
    "gemini_api_key",
    "tenant_key",
    "wc_consumer_key",
    "wc_consumer_secret",
}


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


def bind_observability_context(
    *,
    tenant_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    **extra: Any,
) -> None:
    """Bind request-scoped logging context to structlog contextvars."""
    values: dict[str, Any] = {}
    if tenant_id:
        values["tenant_id"] = tenant_id
    if session_id:
        values["session_id"] = session_id
    if request_id:
        values["request_id"] = request_id
    values.update({key: value for key, value in extra.items() if value is not None})
    if values:
        structlog.contextvars.bind_contextvars(**values)


def clear_observability_context() -> None:
    """Clear all bound request-scoped logging context."""
    structlog.contextvars.clear_contextvars()


def safe_preview(value: str | None, max_chars: int | None = None) -> str:
    """Return a short safe preview string for optional debug logging."""
    text = str(value or "")
    limit = max(1, max_chars or settings.trace_preview_max_chars)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def redact_sensitive_data(value: Any) -> Any:
    """Redact common sensitive fields before logging structured payloads."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, inner_value in value.items():
            if str(key).strip().lower() in _SENSITIVE_FIELD_NAMES:
                redacted[key] = _REDACTED
            else:
                redacted[key] = redact_sensitive_data(inner_value)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    return value
