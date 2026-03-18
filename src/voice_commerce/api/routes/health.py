from __future__ import annotations
import time

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from voice_commerce.config.settings import settings


router = APIRouter()

log = structlog.get_logger(__name__)
 
# Track when the server started (used in the health response)
_server_start_time = time.time()

class HealthResponse(BaseModel):
    """Response model for GET /health (liveness check)."""
    status: str
    service: str
    uptime_seconds: float
    version: str 
    debug_mode: bool


class ReadyResponse(BaseModel):
    """Response model for GET /ready (readiness check)."""
    status: str

    checks: dict[str, str]
    # Individual check results: {"gemini": "ok", "qdrant": "not_configured"}






@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness check",
    description="Returns 200 if the server process is alive. Used by Docker, load balancers, and monitoring.",
)
async def health_check() -> HealthResponse:

    uptime = time.time() - _server_start_time
    log.debug("health_check_called", uptime_seconds=round(uptime, 1))

    return HealthResponse(
        status="ok",
        service="voice_commerce_agent",
        uptime_seconds=round(uptime, 1),
        version=settings.app_version,
        debug_mode=settings.app_debug
    )


@router.get(
    "/ready",
    response_model=ReadyResponse,
    summary="Readiness check",  
    description="Returns 200 if the server is ready to handle requests. Checks dependencies like Gemini API key.",
)
async def readiness_check() -> ReadyResponse:
    """
    Readiness check endpoint.
 
    Checks whether the application is ready to handle real traffic.
    Returns 200 only when all required dependencies are available.
 
    Phase 1: Only checks configuration.
    Phase 2+: Will also ping Gemini API.
    Phase 6+: Will also check WooCommerce connectivity.
    Phase 7+: Will also check Qdrant connectivity.
 
    WHY SEPARATE FROM /health:
        Liveness (/health) = "Is the process alive?" → restart if no
        Readiness (/ready)  = "Is the app ready?"    → stop sending traffic if no
        A container can be alive but not ready (still loading ML model).
        Kubernetes and most load balancers use both checks separately.
    """

    checks: dict[str, str] = {}
    # Check 1: Is Gemini API key configured?
    if settings.gemini_api_key:
        checks["gemini_configured"] = "ok"
    else:
        checks["gemini_configured"] = "missing_api_key"

    is_ready = settings.gemini_api_key != ""
 
    log.debug("readiness_check_called", checks=checks, is_ready=is_ready)



    return ReadyResponse(
            status="ready" if is_ready else "not_ready",
            checks=checks,
        )

