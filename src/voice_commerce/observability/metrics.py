from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Gauge, Info, generate_latest

from voice_commerce.config.settings import settings

APP_INFO = Info("voice_app", "Build and runtime info for the voice commerce app")
READY_STATE = Gauge("voice_ready_state", "Current app readiness state")
ACTIVE_SESSIONS = Gauge("voice_active_sessions", "Number of active voice sessions")


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
