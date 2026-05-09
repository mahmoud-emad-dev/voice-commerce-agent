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
