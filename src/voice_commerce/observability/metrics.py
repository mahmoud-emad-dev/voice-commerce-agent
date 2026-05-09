from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, Info, generate_latest

from voice_commerce.config.settings import settings

APP_INFO = Info("voice_app", "Build and runtime info for the voice commerce app")
READY_STATE = Gauge("voice_ready_state", "Current app readiness state")
ACTIVE_SESSIONS = Gauge("voice_active_sessions", "Number of active voice sessions")
STARTUP_DURATION = Histogram(
    "voice_startup_duration_seconds",
    "Total app startup duration until lifespan initialization is complete",
)
STARTUP_STEP_DURATION = Histogram(
    "voice_startup_step_duration_seconds",
    "Startup and warmup step duration by step and status",
    labelnames=("step", "status"),
)
STARTUP_STEP_TOTAL = Counter(
    "voice_startup_steps_total",
    "Count of startup and warmup steps by step and status",
    labelnames=("step", "status"),
)
TOOL_CALLS_TOTAL = Counter(
    "voice_tool_calls_total",
    "Tool call count by tenant, tool name, and status",
    labelnames=("tenant_id", "tool_name", "status"),
)
TOOL_CALL_DURATION = Histogram(
    "voice_tool_call_duration_seconds",
    "Tool call duration by tenant, tool name, and status",
    labelnames=("tenant_id", "tool_name", "status"),
)
RAG_SEARCHES_TOTAL = Counter(
    "voice_rag_searches_total",
    "RAG search count by tenant and status",
    labelnames=("tenant_id", "status"),
)
RAG_SEARCH_DURATION = Histogram(
    "voice_rag_search_duration_seconds",
    "RAG search duration by tenant and status",
    labelnames=("tenant_id", "status"),
)
RAG_SEARCH_RESULTS = Histogram(
    "voice_rag_search_results_count",
    "RAG search result counts by tenant",
    labelnames=("tenant_id",),
    buckets=(0, 1, 2, 3, 5, 10, 25, 50),
)
EMBEDDING_DURATION = Histogram(
    "voice_embedding_duration_seconds",
    "Embedding duration by operation and status",
    labelnames=("operation", "status"),
)
QDRANT_QUERY_DURATION = Histogram(
    "voice_qdrant_query_duration_seconds",
    "Qdrant query duration by tenant and status",
    labelnames=("tenant_id", "status"),
)
QDRANT_UPSERT_DURATION = Histogram(
    "voice_qdrant_upsert_duration_seconds",
    "Qdrant upsert duration by tenant and status",
    labelnames=("tenant_id", "status"),
)
QDRANT_POINTS_UPSERTED_TOTAL = Counter(
    "voice_qdrant_points_upserted_total",
    "Total Qdrant points upserted by tenant",
    labelnames=("tenant_id",),
)
GEMINI_SESSION_OPEN_DURATION = Histogram(
    "voice_gemini_session_open_duration_seconds",
    "Gemini session open duration by tenant, model, and status",
    labelnames=("tenant_id", "model", "status"),
)
GEMINI_SESSIONS_TOTAL = Counter(
    "voice_gemini_sessions_total",
    "Gemini session outcomes by tenant, model, and status",
    labelnames=("tenant_id", "model", "status"),
)
GEMINI_SESSION_ERRORS_TOTAL = Counter(
    "voice_gemini_session_errors_total",
    "Gemini session error count by tenant, model, and reason",
    labelnames=("tenant_id", "model", "reason"),
)
GEMINI_RECONNECTS_TOTAL = Counter(
    "voice_gemini_reconnects_total",
    "Gemini reconnect or go-away count by tenant and reason",
    labelnames=("tenant_id", "reason"),
)
TURNS_TOTAL = Counter(
    "voice_turns_total",
    "Completed voice turns by tenant, input mode, and status",
    labelnames=("tenant_id", "input_mode", "status"),
)
TURN_DURATION = Histogram(
    "voice_turn_duration_seconds",
    "Voice turn duration by tenant, input mode, and status",
    labelnames=("tenant_id", "input_mode", "status"),
)
TIME_TO_FIRST_AUDIO = Histogram(
    "voice_time_to_first_audio_seconds",
    "Time to first output audio by tenant, input mode, and status",
    labelnames=("tenant_id", "input_mode", "status"),
)
TIME_TO_FIRST_TRANSCRIPT = Histogram(
    "voice_time_to_first_transcript_seconds",
    "Time to first output transcript by tenant, input mode, and status",
    labelnames=("tenant_id", "input_mode", "status"),
)
AUDIO_INPUT_BYTES_TOTAL = Counter(
    "voice_audio_input_bytes_total",
    "Audio input bytes streamed from the browser by tenant",
    labelnames=("tenant_id",),
)
AUDIO_OUTPUT_BYTES_TOTAL = Counter(
    "voice_audio_output_bytes_total",
    "Audio output bytes streamed to the browser by tenant",
    labelnames=("tenant_id",),
)
AUDIO_INPUT_SECONDS_TOTAL = Counter(
    "voice_audio_input_seconds_total",
    "Approximate input audio seconds sent from the browser by tenant",
    labelnames=("tenant_id",),
)
AUDIO_OUTPUT_SECONDS_TOTAL = Counter(
    "voice_audio_output_seconds_total",
    "Approximate output audio seconds sent to the browser by tenant",
    labelnames=("tenant_id",),
)
AUDIO_CHUNKS_IN_TOTAL = Counter(
    "voice_audio_chunks_in_total",
    "Input audio chunks received from the browser by tenant",
    labelnames=("tenant_id",),
)
AUDIO_CHUNKS_OUT_TOTAL = Counter(
    "voice_audio_chunks_out_total",
    "Output audio chunks sent to the browser by tenant",
    labelnames=("tenant_id",),
)


def initialize_base_metrics() -> None:
    """Populate base metric labels that are stable for the current process."""
    APP_INFO.info(
        {
            "app_env": settings.app_env,
            "app_version": settings.app_version,
            "qdrant_mode": settings.qdrant_mode,
            "tenant_mode": settings.tenant_mode,
        }
    )


def set_ready_state(is_ready: bool) -> None:
    """Update the simple readiness gauge for monitoring and dashboards."""
    READY_STATE.set(1 if is_ready else 0)


def render_metrics() -> bytes:
    """Render the current Prometheus registry in text exposition format."""
    return generate_latest()


def metrics_content_type() -> str:
    """Return the Prometheus exposition content type."""
    return CONTENT_TYPE_LATEST


def observe_startup_step(step: str, duration_s: float, *, status: str) -> None:
    """Record the duration and outcome of one startup or warmup step."""
    STARTUP_STEP_DURATION.labels(step=step, status=status).observe(duration_s)
    STARTUP_STEP_TOTAL.labels(step=step, status=status).inc()


def observe_tool_call(
    tenant_id: str | None,
    tool_name: str,
    duration_s: float,
    *,
    status: str,
) -> None:
    """Record one tool call outcome and duration."""
    resolved_tenant_id = tenant_id or "demo"
    TOOL_CALLS_TOTAL.labels(
        tenant_id=resolved_tenant_id,
        tool_name=tool_name,
        status=status,
    ).inc()
    TOOL_CALL_DURATION.labels(
        tenant_id=resolved_tenant_id,
        tool_name=tool_name,
        status=status,
    ).observe(duration_s)


def observe_rag_search(
    tenant_id: str | None,
    duration_s: float,
    *,
    status: str,
    result_count: int,
) -> None:
    """Record one RAG search outcome, duration, and result count."""
    resolved_tenant_id = tenant_id or "demo"
    RAG_SEARCHES_TOTAL.labels(tenant_id=resolved_tenant_id, status=status).inc()
    RAG_SEARCH_DURATION.labels(tenant_id=resolved_tenant_id, status=status).observe(duration_s)
    RAG_SEARCH_RESULTS.labels(tenant_id=resolved_tenant_id).observe(result_count)


def observe_embedding(operation: str, duration_s: float, *, status: str) -> None:
    """Record one embedding operation duration and outcome."""
    EMBEDDING_DURATION.labels(operation=operation, status=status).observe(duration_s)


def observe_qdrant_query(tenant_id: str | None, duration_s: float, *, status: str) -> None:
    """Record one Qdrant query duration and outcome."""
    QDRANT_QUERY_DURATION.labels(tenant_id=tenant_id or "demo", status=status).observe(duration_s)


def observe_qdrant_upsert(
    tenant_id: str | None,
    duration_s: float,
    *,
    status: str,
    point_count: int,
) -> None:
    """Record one Qdrant upsert duration, outcome, and affected point count."""
    resolved_tenant_id = tenant_id or "demo"
    QDRANT_UPSERT_DURATION.labels(tenant_id=resolved_tenant_id, status=status).observe(duration_s)
    if point_count > 0:
        QDRANT_POINTS_UPSERTED_TOTAL.labels(tenant_id=resolved_tenant_id).inc(point_count)


def increment_active_sessions() -> None:
    """Increment the live active-session gauge."""
    ACTIVE_SESSIONS.inc()


def decrement_active_sessions() -> None:
    """Decrement the live active-session gauge."""
    ACTIVE_SESSIONS.dec()


def observe_gemini_session_open(
    tenant_id: str | None,
    model: str,
    duration_s: float,
    *,
    status: str,
) -> None:
    """Record one Gemini session open attempt and duration."""
    resolved_tenant_id = tenant_id or "demo"
    GEMINI_SESSION_OPEN_DURATION.labels(
        tenant_id=resolved_tenant_id,
        model=model,
        status=status,
    ).observe(duration_s)
    GEMINI_SESSIONS_TOTAL.labels(
        tenant_id=resolved_tenant_id,
        model=model,
        status=status,
    ).inc()


def observe_gemini_session_error(tenant_id: str | None, model: str, *, reason: str) -> None:
    """Record one Gemini session-side error by reason."""
    GEMINI_SESSION_ERRORS_TOTAL.labels(
        tenant_id=tenant_id or "demo",
        model=model,
        reason=reason,
    ).inc()


def observe_gemini_reconnect(tenant_id: str | None, *, reason: str) -> None:
    """Record one reconnect or go-away event for a tenant."""
    GEMINI_RECONNECTS_TOTAL.labels(tenant_id=tenant_id or "demo", reason=reason).inc()


def observe_turn(
    tenant_id: str | None,
    input_mode: str,
    duration_s: float,
    *,
    status: str,
) -> None:
    """Record one completed turn duration and outcome."""
    resolved_tenant_id = tenant_id or "demo"
    TURNS_TOTAL.labels(tenant_id=resolved_tenant_id, input_mode=input_mode, status=status).inc()
    TURN_DURATION.labels(
        tenant_id=resolved_tenant_id,
        input_mode=input_mode,
        status=status,
    ).observe(duration_s)


def observe_time_to_first_audio(
    tenant_id: str | None,
    input_mode: str,
    duration_s: float,
    *,
    status: str,
) -> None:
    """Record time to first output audio for one turn."""
    TIME_TO_FIRST_AUDIO.labels(
        tenant_id=tenant_id or "demo",
        input_mode=input_mode,
        status=status,
    ).observe(duration_s)


def observe_time_to_first_transcript(
    tenant_id: str | None,
    input_mode: str,
    duration_s: float,
    *,
    status: str,
) -> None:
    """Record time to first output transcript for one turn."""
    TIME_TO_FIRST_TRANSCRIPT.labels(
        tenant_id=tenant_id or "demo",
        input_mode=input_mode,
        status=status,
    ).observe(duration_s)


def observe_audio_input(tenant_id: str | None, byte_count: int, seconds: float) -> None:
    """Record one inbound browser audio chunk by bytes and estimated seconds."""
    resolved_tenant_id = tenant_id or "demo"
    AUDIO_CHUNKS_IN_TOTAL.labels(tenant_id=resolved_tenant_id).inc()
    AUDIO_INPUT_BYTES_TOTAL.labels(tenant_id=resolved_tenant_id).inc(byte_count)
    AUDIO_INPUT_SECONDS_TOTAL.labels(tenant_id=resolved_tenant_id).inc(seconds)


def observe_audio_output(tenant_id: str | None, byte_count: int, seconds: float) -> None:
    """Record one outbound Gemini audio chunk by bytes and estimated seconds."""
    resolved_tenant_id = tenant_id or "demo"
    AUDIO_CHUNKS_OUT_TOTAL.labels(tenant_id=resolved_tenant_id).inc()
    AUDIO_OUTPUT_BYTES_TOTAL.labels(tenant_id=resolved_tenant_id).inc(byte_count)
    AUDIO_OUTPUT_SECONDS_TOTAL.labels(tenant_id=resolved_tenant_id).inc(seconds)
