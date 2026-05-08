from __future__ import annotations

import structlog

from voice_commerce.observability.logging import build_structlog_processors


def test_build_structlog_processors_uses_console_renderer_when_json_disabled() -> None:
    processors = build_structlog_processors(log_json=False)

    assert isinstance(processors[-1], structlog.dev.ConsoleRenderer)


def test_build_structlog_processors_uses_json_renderer_when_json_enabled() -> None:
    processors = build_structlog_processors(log_json=True)

    assert isinstance(processors[-1], structlog.processors.JSONRenderer)
