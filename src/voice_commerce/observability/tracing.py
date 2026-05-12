from __future__ import annotations

from typing import Any, Protocol

from voice_commerce.config.settings import settings


class Tracer(Protocol):
    def start_session(
        self,
        session_id: str,
        tenant_id: str,
        *,
        model: str,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    def finish_session(
        self,
        session_id: str,
        *,
        tenant_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...
    def record_event(
        self,
        name: str,
        *,
        session_id: str | None = None,
        tenant_id: str | None = None,
        input_payload: Any = None,
        output_payload: Any = None,
        metadata: dict[str, Any] | None = None,
        level: str | None = None,
    ) -> None: ...
    def record_observation(
        self,
        name: str,
        *,
        as_type: str,
        session_id: str | None = None,
        tenant_id: str | None = None,
        input_payload: Any = None,
        output_payload: Any = None,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
        usage_details: dict[str, int] | None = None,
        cost_details: dict[str, float] | None = None,
    ) -> None: ...
    def flush(self) -> None: ...


class NoOpTracer:
    def start_session(
        self,
        session_id: str,
        tenant_id: str,
        *,
        model: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        return None

    def finish_session(
        self,
        session_id: str,
        *,
        tenant_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        return None

    def record_event(
        self,
        name: str,
        *,
        session_id: str | None = None,
        tenant_id: str | None = None,
        input_payload: Any = None,
        output_payload: Any = None,
        metadata: dict[str, Any] | None = None,
        level: str | None = None,
    ) -> None:
        return None

    def record_observation(
        self,
        name: str,
        *,
        as_type: str,
        session_id: str | None = None,
        tenant_id: str | None = None,
        input_payload: Any = None,
        output_payload: Any = None,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
        usage_details: dict[str, int] | None = None,
        cost_details: dict[str, float] | None = None,
    ) -> None:
        return None

    def flush(self) -> None:
        return None


_tracer_instance: Tracer | None = None


def reset_tracer() -> None:
    global _tracer_instance
    _tracer_instance = None


def get_tracer() -> Tracer:
    global _tracer_instance
    if _tracer_instance is not None:
        return _tracer_instance

    tracing_enabled = settings.llm_tracing_enabled and settings.langfuse_enabled
    credentials_present = bool(settings.langfuse_public_key and settings.langfuse_secret_key)
    if tracing_enabled and credentials_present:
        from voice_commerce.observability.langfuse_tracer import LangfuseTracer

        _tracer_instance = LangfuseTracer()
    else:
        _tracer_instance = NoOpTracer()
    return _tracer_instance
