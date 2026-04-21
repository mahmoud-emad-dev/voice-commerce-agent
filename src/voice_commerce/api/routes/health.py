# src/voice_commerce/api/routes/health.py
# ==============================================================================
# PURPOSE: Provides Liveness and Readiness probes for the FastAPI server.
#
# WHY THIS FILE EXISTS:
#   In production (Docker/Kubernetes), the infrastructure needs to know if the 
#   server is alive (Liveness) and if it is fully connected to its dependencies 
#   like Gemini or WooCommerce (Readiness) before routing user traffic to it.
# ==============================================================================

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from voice_commerce.config.settings import settings
from voice_commerce.core.rag import embedder
from voice_commerce.services.rag_service import get_rag_service


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






@router.get("/health",
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
async def readiness_check(response: Response) -> ReadyResponse:
    """
    Readiness check endpoint.
 
    Checks whether the application is ready to handle real traffic.
    Returns 200 only when all required dependencies are available.
 
    Phase 1: Only checks configuration.
    Phase 2+: Will also ping Gemini API.
    Phase 6+: Will also check WooCommerce connectivity.
    Phase 7+: Will also check Qdrant connectivity.
    
    """
    rag = get_rag_service()
    checks: dict[str, str] = {}

    checks["gemini_configured"] = "ok" if settings.is_gemini_configured else "missing_api_key"
    checks["embedder"] = "ready" if embedder.is_ready() else "warming_up"
    checks["rag_catalog"] = "ready" if rag.is_ready else "syncing"

    embedder_error = embedder.last_error()
    if embedder_error:
        checks["embedder"] = "load_failed"



    # # Check 2: Is WooCommerce configured?
    # if settings.is_woocommerce_configured:
    #     checks["woocommerce_configured"] = "ok"
    # else:
    #     checks["woocommerce_configured"] = "not_configured_yet"
    #     # Note: NOT an error in Phase 1-5. WooCommerce is added in Phase 6.
 
    # # Check 3: What Qdrant mode are we using?
    # checks["qdrant_mode"] = settings.qdrant_mode
    is_ready = (
        settings.is_gemini_configured
        and embedder.is_ready()
        and rag.is_ready
        and not embedder_error
    )
    readiness_status = "ready" if is_ready else "not_ready"
    log.debug("readiness_check_called", checks=checks, is_ready=is_ready)
    if not is_ready:
        log.warning("readiness_check_failed", checks=checks)
    else:
        log.debug("readiness_check_passed")

    response.status_code = (
        status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return ReadyResponse(status=readiness_status, checks=checks)

