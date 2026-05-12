from __future__ import annotations

from voice_commerce.config.settings import settings
from voice_commerce.observability.tracing import NoOpTracer, get_tracer, reset_tracer


class FakeLangfuseTracer:
    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.events: list[str] = []

    def start_session(self, session_id: str, tenant_id: str, *, model: str, metadata=None) -> None:
        self.started.append((session_id, tenant_id))

    def finish_session(self, session_id: str, *, tenant_id=None, metadata=None) -> None:
        self.events.append("finish")

    def record_event(self, name: str, **kwargs) -> None:
        self.events.append(name)

    def record_observation(self, name: str, **kwargs) -> None:
        self.events.append(name)

    def flush(self) -> None:
        self.events.append("flush")


def test_get_tracer_returns_noop_when_disabled(monkeypatch) -> None:
    reset_tracer()
    monkeypatch.setattr(settings, "llm_tracing_enabled", False)
    monkeypatch.setattr(settings, "langfuse_enabled", False)

    tracer = get_tracer()

    assert isinstance(tracer, NoOpTracer)


def test_get_tracer_returns_langfuse_tracer_when_enabled(monkeypatch) -> None:
    reset_tracer()
    monkeypatch.setattr(settings, "llm_tracing_enabled", True)
    monkeypatch.setattr(settings, "langfuse_enabled", True)
    monkeypatch.setattr(settings, "langfuse_public_key", "pk")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk")
    monkeypatch.setattr(
        "voice_commerce.observability.langfuse_tracer.LangfuseTracer",
        FakeLangfuseTracer,
    )

    tracer = get_tracer()
    tracer.start_session("sess-1", "demo", model=settings.gemini_model)
    tracer.record_event("event-one")
    tracer.flush()

    assert isinstance(tracer, FakeLangfuseTracer)
    assert tracer.started == [("sess-1", "demo")]
    assert tracer.events == ["event-one", "flush"]
