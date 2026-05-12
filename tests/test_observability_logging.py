from __future__ import annotations

import structlog

from voice_commerce.observability.logging import (
    bind_observability_context,
    build_structlog_processors,
    clear_observability_context,
    redact_sensitive_data,
    safe_preview,
)


def test_build_structlog_processors_uses_console_renderer_when_json_disabled() -> None:
    processors = build_structlog_processors(log_json=False)

    assert isinstance(processors[-1], structlog.dev.ConsoleRenderer)


def test_build_structlog_processors_uses_json_renderer_when_json_enabled() -> None:
    processors = build_structlog_processors(log_json=True)

    assert isinstance(processors[-1], structlog.processors.JSONRenderer)


def test_bind_and_clear_observability_context() -> None:
    clear_observability_context()

    bind_observability_context(tenant_id="demo", session_id="sess-1", request_id="req-1")
    merged = structlog.contextvars.get_contextvars()
    assert merged["tenant_id"] == "demo"
    assert merged["session_id"] == "sess-1"
    assert merged["request_id"] == "req-1"

    clear_observability_context()
    assert structlog.contextvars.get_contextvars() == {}


def test_redact_sensitive_data_redacts_nested_sensitive_keys() -> None:
    payload = {
        "tenant_key": "secret",
        "nested": {"api_key": "another-secret", "ok": "value"},
    }

    redacted = redact_sensitive_data(payload)

    assert redacted["tenant_key"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert redacted["nested"]["ok"] == "value"


def test_safe_preview_truncates_long_values() -> None:
    assert safe_preview("abcdefgh", max_chars=5) == "abcde..."
