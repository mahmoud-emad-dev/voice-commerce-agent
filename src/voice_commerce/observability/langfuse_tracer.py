from __future__ import annotations

from typing import Any

import structlog
from langfuse import Langfuse

from voice_commerce.config.settings import settings
from voice_commerce.observability.logging import redact_sensitive_data, safe_preview

log = structlog.get_logger(__name__)


class LangfuseTracer:
    """Small Langfuse adapter that keeps SDK usage isolated to one file."""

    def __init__(self) -> None:
        self._client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        self._trace_ids: dict[str, str] = {}

    def _safe_payload(self, payload: Any) -> Any:
        if payload is None:
            return None
        if not settings.trace_payload_previews:
            return None
        if isinstance(payload, str):
            return safe_preview(payload)
        if isinstance(payload, dict):
            return redact_sensitive_data(payload)
        return payload

    def _trace_context(
        self,
        session_id: str | None,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not session_id:
            return None
        trace_id = self._trace_ids.get(session_id)
        if not trace_id:
            trace_id = self._client.create_trace_id()
            self._trace_ids[session_id] = trace_id
        context = {"trace_id": trace_id, "session_id": session_id}
        if tenant_id:
            context["user_id"] = tenant_id
        return context

    def start_session(
        self,
        session_id: str,
        tenant_id: str,
        *,
        model: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._client.create_event(
                trace_context=self._trace_context(session_id, tenant_id),
                name="voice_session_started",
                metadata=redact_sensitive_data(metadata or {})
                | {"tenant_id": tenant_id, "model": model},
            )
        except Exception as exc:
            log.warning("langfuse_session_start_failed", error=str(exc))

    def finish_session(
        self,
        session_id: str,
        *,
        tenant_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._client.create_event(
                trace_context=self._trace_context(session_id, tenant_id),
                name="voice_session_finished",
                metadata=redact_sensitive_data(metadata or {}),
            )
        except Exception as exc:
            log.warning("langfuse_session_finish_failed", error=str(exc))

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
        try:
            self._client.create_event(
                trace_context=self._trace_context(session_id, tenant_id),
                name=name,
                input=self._safe_payload(input_payload),
                output=self._safe_payload(output_payload),
                metadata=redact_sensitive_data(metadata or {}),
                level=level,
            )
        except Exception as exc:
            log.warning("langfuse_event_failed", event=name, error=str(exc))

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
        try:
            self._client.start_observation(
                trace_context=self._trace_context(session_id, tenant_id),
                name=name,
                as_type=as_type,
                input=self._safe_payload(input_payload),
                output=self._safe_payload(output_payload),
                metadata=redact_sensitive_data(metadata or {}),
                model=model,
                usage_details=usage_details,
                cost_details=cost_details,
            )
        except Exception as exc:
            log.warning("langfuse_observation_failed", observation=name, error=str(exc))

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception as exc:
            log.warning("langfuse_flush_failed", error=str(exc))
