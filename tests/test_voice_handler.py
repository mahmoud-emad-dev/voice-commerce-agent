# =============================================================================
# tests/test_voice_handler.py
# =============================================================================
#
# PURPOSE:
#   Tests for the voice WebSocket endpoint and handler.
#
# TESTING WEBSOCKETS IN FASTAPI:
#   FastAPI provides a WebSocketTestClient context manager that lets you test
#   WebSocket endpoints without running a real server:
#
#   with client.websocket_connect("/ws/voice") as ws:
#       ws.send_text("hello")
#       response = ws.receive_text()
#
#   IMPORTANT: This uses the synchronous TestClient (from starlette).
#   WHY SYNC HERE: WebSocket testing in FastAPI works differently from
#   async HTTP testing — the WebSocketTestClient manages the event loop
#   internally. This is a known limitation of FastAPI's test utilities.
#
# TESTING STRATEGY:
#   We can't easily mock the Gemini API in these tests (would need to
#   mock google.genai deeply). So we:
#   1. Test the WebSocket connection mechanics (connect, receive initial status)
#   2. Mark Gemini-dependent tests as @pytest.mark.integration
#      (run manually when you have a real API key)
#   3. Phase 3 will add dependency injection that makes mocking easier
#
# =============================================================================

from __future__ import annotations

import json
from typing import cast

import pytest
from fastapi.testclient import TestClient

from voice_commerce.core.voice.gemini_live_handler import GeminiLiveHandler
from voice_commerce.handlers.voice_websocket_handler import VoiceWebSocketHandler
from voice_commerce.main import create_app


@pytest.fixture(scope="module")
def sync_client():
    """
    Synchronous test client for WebSocket tests.
    WHY SYNC: FastAPI's WebSocketTestClient requires the sync TestClient.
    The async AsyncClient we use for HTTP tests doesn't support WebSocket testing.
    """
    app = create_app()
    return TestClient(app)


class TestVoiceWebSocketConnection:
    """Tests for WebSocket connection establishment."""

    def test_websocket_connects_successfully(self, sync_client: TestClient) -> None:
        """
        The WebSocket endpoint should accept connections.
        If this fails, the route is not registered correctly in main.py.
        """
        try:
            with sync_client.websocket_connect("/ws/voice") as ws:
                # Connection opened successfully
                # Receive the initial status message the server sends on connect
                raw = ws.receive_text()
                data = json.loads(raw)
                # Server sends either a status or connected message first
                assert "type" in data
        except Exception as e:
            pytest.fail(f"WebSocket connection failed: {e}")

    def test_websocket_receives_initial_status(self, sync_client: TestClient) -> None:
        """
        Server should send an initial status message upon connection.
        This tells the browser the connection state before Gemini is ready.
        """
        with sync_client.websocket_connect("/ws/voice") as ws:
            # First message should be a status update
            raw = ws.receive_text()
            data = json.loads(raw)
            assert data.get("type") == "status", (
                f"Expected first message type='status', got: {data}"
            )

    def test_websocket_with_session_id_query_param(self, sync_client: TestClient) -> None:
        """
        WebSocket should accept an optional session_id query parameter.
        Used for tracking and session resumption in Phase 11.
        """
        custom_session = "test-session-123"
        try:
            with sync_client.websocket_connect(
                f"/ws/voice?session_id={custom_session}"
            ) as ws:
                # Just verify connection works with the param
                raw = ws.receive_text()
                data = json.loads(raw)
                assert "type" in data
        except Exception as e:
            pytest.fail(f"Connection with session_id failed: {e}")

    def test_websocket_without_session_id_auto_generates(
        self, sync_client: TestClient
    ) -> None:
        """
        Connecting without session_id should work fine.
        Server auto-generates a session ID.
        """
        # Simply verify no exception is raised when connecting without session_id
        with sync_client.websocket_connect("/ws/voice") as ws:
            raw = ws.receive_text()
            assert raw  # Something was received


class TestVoiceWebSocketProtocol:
    """Tests for the message protocol format."""

    def test_status_message_has_required_fields(self, sync_client: TestClient) -> None:
        """
        Status messages must have 'type' and 'status' fields.
        Browser UI depends on this structure.
        """
        with sync_client.websocket_connect("/ws/voice") as ws:
            raw = ws.receive_text()
            data = json.loads(raw)

            if data.get("type") == "status":
                assert "status" in data, "Status message missing 'status' field"

    def test_server_sends_valid_json(self, sync_client: TestClient) -> None:
        """
        All text frames from the server must be valid JSON.
        The browser's JSON.parse() will throw on invalid JSON.
        """
        with sync_client.websocket_connect("/ws/voice") as ws:
            raw = ws.receive_text()
            try:
                json.loads(raw)
            except json.JSONDecodeError as e:
                pytest.fail(f"Server sent invalid JSON: {raw!r}. Error: {e}")


class FakeGeminiSession:
    """Small fake for queueing tests that don't need the real Gemini API."""

    def __init__(self, is_connected: bool = False) -> None:
        self.is_connected = is_connected
        self.sent_texts: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent_texts.append(text)


async def test_user_text_is_buffered_until_gemini_connects() -> None:
    handler = VoiceWebSocketHandler(session_id="buffered-text-test")
    gemini = FakeGeminiSession(is_connected=False)
    handler._gemini = cast(GeminiLiveHandler, gemini)

    sent_immediately = await handler._queue_or_send_user_text(
        "hello",
        cast(GeminiLiveHandler, gemini),
    )

    assert sent_immediately is False
    assert handler._pending_texts == ["hello"]
    assert gemini.sent_texts == []

    gemini.is_connected = True
    flushed_count = await handler._flush_pending_texts(cast(GeminiLiveHandler, gemini))

    assert flushed_count == 1
    assert handler._pending_texts == []
    assert gemini.sent_texts == ["hello"]


@pytest.mark.integration
class TestVoiceWebSocketGemini:
    """
    Integration tests that require a real Gemini API key.
    Run with: uv run pytest tests/ -m integration

    WHY MARKED integration:
        These tests make real API calls to Google's servers.
        - Require GEMINI_API_KEY in .env
        - Cost money (Gemini API usage)
        - Are slow (network round trips)
        - Should NOT run in CI without secrets configured
    """

    def test_text_message_receives_response(self, sync_client: TestClient) -> None:
        """
        Sending a text message should eventually receive an AI response.
        Requires real Gemini API key.
        """
        with sync_client.websocket_connect("/ws/voice") as ws:
            # Wait for ready status
            messages = []
            for _ in range(5):  # Receive up to 5 messages waiting for "done"/"ready"
                raw = ws.receive_text()
                data = json.loads(raw)
                messages.append(data)
                if data.get("type") == "status" and data.get("status") in ("done", "ready"):
                    break

            # Send a simple greeting
            ws.send_text(json.dumps({"type": "text", "text": "Hello"}))

            # Collect responses until we get a "done" status
            response_texts = []
            got_done = False
            for _ in range(20):  # Max 20 messages to avoid infinite loop
                raw = ws.receive_text()
                data = json.loads(raw)
                if data.get("type") == "text":
                    response_texts.append(data.get("text", ""))
                elif data.get("type") == "status" and data.get("status") == "done":
                    got_done = True
                    break

            assert len(response_texts) > 0, "No text response received from Gemini"
            assert got_done, "Never received 'done' status after AI response"

            full_response = "".join(response_texts)
            assert len(full_response) > 0, "AI response was empty"
