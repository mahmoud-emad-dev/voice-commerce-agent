# src/voice_commerce/api/routes/voice.py
# ==============================================================================
# PURPOSE: The WebSocket endpoint for the Voice Commerce Agent.
#
# WHY THIS FILE EXISTS:
#   This is a "Thin Router". Its only job is to accept the WebSocket upgrade,
#   extract the session_id from the URL, and immediately hand control over 
#   to the VoiceWebSocketHandler. It contains NO business logic.
# ==============================================================================

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Query, WebSocket

from voice_commerce.config.settings import settings
from voice_commerce.handlers.voice_websocket_handler import VoiceWebSocketHandler
from voice_commerce.observability.logging import (
    bind_observability_context,
    clear_observability_context,
)
from voice_commerce.services.tenant_service import TenantResolutionError, get_tenant_service

router = APIRouter()
log = structlog.get_logger(__name__)

@router.websocket("/voice")
async def voice_endpoint(
    websocket: WebSocket,
    session_id: str | None = Query(
        default=None,
        description=(
            "Optional session identifier for tracking and resuming conversations. "
            "If not provided, a new session ID is generated automatically."
        ),
    ),
    tenant_id: str | None = Query(default=None, description="Tenant identifier for this store."),
    tenant_key: str | None = Query(default=None, description="Tenant API key for this store."),
) -> None:
    """
    WebSocket endpoint for voice/text conversations.
 
    Each client connection gets its own VoiceWebSocketHandler instance,
    which manages the session state and Gemini interaction for that client.
    """
    # Generate a session ID if the browser didn't provide one.
    # A UUID4 is random and collision-resistant — good enough for session IDs.
    effective_session_id = session_id or str(uuid.uuid4())
    allow_demo_fallback = bool(settings.app_debug or settings.tenant_mode.strip().lower() == "demo")
    try:
        bind_observability_context(session_id=effective_session_id, tenant_id=tenant_id)
        tenant = await get_tenant_service().resolve_tenant(
            tenant_id,
            tenant_key,
            allow_demo_fallback=allow_demo_fallback,
        )
        bind_observability_context(tenant_id=tenant.tenant_id)
    except TenantResolutionError as exc:
        log.warning("voice_tenant_resolution_failed", tenant_id=tenant_id, error=str(exc))
        await websocket.close(code=1008, reason=str(exc))
        return

    # Hand off the entire connection lifecycle to the dedicated handler
    try:
        handler = VoiceWebSocketHandler(session_id=effective_session_id, tenant_id=tenant.tenant_id)
        await handler.handle(websocket)
    finally:
        clear_observability_context()

 
