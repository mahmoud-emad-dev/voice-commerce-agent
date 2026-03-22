from __future__ import annotations
import uuid



import structlog
from fastapi import APIRouter, websockets , Query



from voice_commerce.handlers.voice_websocket_handler import VoiceWebSocketHandler

router = APIRouter()
log = structlog.get_logger(__name__)

@router.websocket("/voice")
async def voice_endpoint(
    websocket: websockets.WebSocket ,
    session_id: str | None = Query(
        default=None,
        description=(
            "Optional session identifier for tracking and resuming conversations. "
            "If not provided, a new session ID is generated automatically."
        ),
    ),
    ) -> None:
    """
    WebSocket endpoint for voice/text conversations.
 
    Each client connection gets its own VoiceWebSocketHandler instance,
    which manages the session state and Gemini interaction for that client.
    """
    # Generate a session ID if the browser didn't provide one.
    # A UUID4 is random and collision-resistant — good enough for session IDs.
    effective_session_id = session_id or str(uuid.uuid4())

    handler = VoiceWebSocketHandler(session_id=effective_session_id)
    await handler.handle(websocket)

 
