# src/voice_commerce/handlers/voice_websocket_handler.py
# ==============================================================================
# PURPOSE: Bridges the Browser's WebSocket and the Gemini API.
#
# WHY THIS FILE EXISTS:
#   This handler manages the two-way real-time data stream. It receives audio
#   from the browser and pipes it to Gemini. It receives audio/tools from
#   Gemini and pipes them to the browser or the Tool Dispatcher.
# ==============================================================================

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from voice_commerce.config.settings import settings
from voice_commerce.core.voice.gemini_live_handler import GeminiLiveHandler
from voice_commerce.core.voice import audio_processor
from voice_commerce.core.tools import tool_dispatcher, cart_tools, checkout_tools
from voice_commerce.core.actions.action_dispatcher import ActionDispatcher

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Protocol constants — all WebSocket message type strings in one place
# ---------------------------------------------------------------------------
MSG_TEXT = "text"
MSG_AUDIO = "audio"
MSG_TRANSCRIPT = "transcript"
MSG_ACTION = "action"
MSG_STATUS = "status"
MSG_ERROR = "error"
MSG_AUDIO_CFG = "audio_config"
MSG_MIC_CONFIG = "mic_config"  # Tells browser what sample rate to capture mic at

STATUS_THINKING = "thinking"
STATUS_RESPONDING = "responding"
STATUS_DONE = "done"
STATUS_READY = "ready"
STATUS_ERROR = "error"

# GLOBAL MEMORY STORE: Keeps transcripts alive across page reloads!
# In a real production app, this would be a database like Redis or Postgres.
GLOBAL_SESSIONS: dict[str, list[dict[str, str]]] = {}
GLOBAL_HANDLES: dict[str, str] = {}  # Stores Google's resumption handles
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


class VoiceWebSocketHandler:
    """
    Manages one WebSocket session from one browser client.

    One instance per connection. Two concurrent async tasks run inside
    handle() for the lifetime of the connection.

    Instance attributes set in __init__:
        session_id    — unique ID for logging and cart isolation
        _transcript   — growing list of {role, text} dicts (persisted in Phase 11)
        _websocket    — set in handle(), used by helper send methods
        _gemini       — set in handle(), used by _browser_to_gemini_task
        _input_mode   — "text" or "audio"; switches when browser sends binary
    """

    def __init__(self, session_id: str | None = None) -> None:
        """Initialize per-connection state for one browser session."""
        self.session_id = session_id or f"sess_{int(time.time() * 1000)}"
        # Fetch old memory from the global store, or start a new list if it's a new session
        if self.session_id not in GLOBAL_SESSIONS:
            GLOBAL_SESSIONS[self.session_id] = []
        self._transcript: list[dict[str, str]] = GLOBAL_SESSIONS[self.session_id]
        self._resumption_handle: str | None = GLOBAL_HANDLES.get(self.session_id)
        self._websocket: WebSocket | None = None
        self._gemini: GeminiLiveHandler | None = None
        self._input_mode: str = "text"
        self._user_started_interaction = False
        self._startup_greeting_sent = False
        self._startup_greeting_task: asyncio.Task[None] | None = None
        self._pending_texts: list[str] = []
        self._pending_texts_lock = asyncio.Lock()
        self._pending_text_flush_task: asyncio.Task[None] | None = None
        self.action_dispatcher = ActionDispatcher()
        log.info("voice_handler_created", session_id=self.session_id)

    @staticmethod
    def _payload_logging_enabled() -> bool:
        return settings.app_debug and settings.debug_payload_logs

    @staticmethod
    def _sanitize_display_text(text: str) -> str:
        """Remove non-display control characters before sending text to the chat UI."""
        if not text:
            return ""
        cleaned = _CONTROL_CHAR_RE.sub("", text)
        return cleaned.strip()

    async def _wait_for_gemini_connected(
        self, gemini: GeminiLiveHandler, timeout_s: float = 2.5
    ) -> bool:
        """
        Wait briefly until Gemini is connected for this handler instance.
        Prevents proactive greeting race conditions at startup/shutdown edges.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._gemini is not gemini:
                return False
            if gemini.is_connected:
                return True
            await asyncio.sleep(0.05)
        return gemini.is_connected and self._gemini is gemini

    async def _flush_pending_texts_locked(self, gemini: GeminiLiveHandler) -> int:
        """Send queued typed inputs to Gemini in the original order."""
        flushed_count = 0

        while self._pending_texts and gemini.is_connected and self._gemini is gemini:
            next_text = self._pending_texts.pop(0)
            await gemini.send_text(next_text)
            flushed_count += 1
            log.info(
                "pending_user_text_flushed",
                session_id=self.session_id,
                remaining=len(self._pending_texts),
                text_length=len(next_text),
            )

        return flushed_count

    async def _flush_pending_texts(self, gemini: GeminiLiveHandler) -> int:
        """Flush pending typed inputs if the Gemini live session is ready."""
        async with self._pending_texts_lock:
            return await self._flush_pending_texts_locked(gemini)

    async def _queue_or_send_user_text(self, user_text: str, gemini: GeminiLiveHandler) -> bool:
        """
        Preserve typed user input across the Gemini startup race.

        Returns True when the text was sent immediately, False when it was buffered.
        """
        async with self._pending_texts_lock:
            self._pending_texts.append(user_text)

            if not gemini.is_connected or self._gemini is not gemini:
                log.info(
                    "user_text_buffered_gemini_not_connected",
                    session_id=self.session_id,
                    pending_count=len(self._pending_texts),
                    text_length=len(user_text),
                )
                return False

            await self._flush_pending_texts_locked(gemini)
            return True

    async def _flush_pending_texts_when_ready(self, gemini: GeminiLiveHandler) -> None:
        """Wait for Gemini to connect, then send any queued typed inputs."""
        try:
            while self._gemini is gemini:
                if await self._wait_for_gemini_connected(gemini, timeout_s=0.5):
                    flushed_count = await self._flush_pending_texts(gemini)
                    if flushed_count:
                        log.info(
                            "pending_user_texts_fully_flushed",
                            session_id=self.session_id,
                            flushed_count=flushed_count,
                        )
                    return
        except asyncio.CancelledError:
            log.debug("pending_text_flush_cancelled", session_id=self.session_id)
            raise

    async def handle(self, websocket: WebSocket) -> None:
        """
        The main entry point for a WebSocket connection.
        Sets up the configs of the WebSocket, opens Gemini, and runs the two communication loops.
        """
        #  ====== Accept the WebSocket connection and save the reference for later use in helper methods.======
        await websocket.accept()
        self._websocket = websocket

        log.info("ws_connected", session_id=self.session_id, client=str(websocket.client))

        # 1  ====== INITIAL SETUP: Send configs and open Gemini session ======
        ##  Send audio output config so browser creates AudioContext at 24kHz
        await self._send_json({"type": MSG_AUDIO_CFG, **audio_processor.get_browser_audio_config()})

        ##  Send microphone capture config so browser knows what rate to capture
        await self._send_json({"type": MSG_MIC_CONFIG, **audio_processor.get_mic_audio_config()})

        await self._send_status(STATUS_THINKING, "Opening AI session...")

        try:
            # 2 ====== Open the Gemini Live session ======
            async with GeminiLiveHandler(
                transcript=self._transcript, resumption_handle=self._resumption_handle
            ) as gemini:
                self._gemini = gemini
                self._pending_text_flush_task = asyncio.create_task(
                    self._flush_pending_texts_when_ready(gemini),
                    name=f"pending_text_flush:{self.session_id}",
                )
                await self._send_status(STATUS_READY, "Ready — speak or type")

                # ── 2.1 Proactive Greeting (Only on first connection) ──────────
                if not self._resumption_handle and len(self._transcript) == 0:

                    async def delayed_greeting():
                        try:
                            await asyncio.sleep(1.5)

                            if self._user_started_interaction:
                                log.info(
                                    "startup_greeting_skipped_user_already_active",
                                    session_id=self.session_id,
                                )
                                return
                            if self._startup_greeting_sent:
                                return

                            ready = await self._wait_for_gemini_connected(gemini, timeout_s=2.5)
                            if not ready:
                                log.info(
                                    "startup_greeting_skipped_not_connected",
                                    session_id=self.session_id,
                                )
                                return

                            self._startup_greeting_sent = True
                            log.info("triggering_proactive_greeting", session_id=self.session_id)
                            await gemini.send_text(
                                "--- SYSTEM: The user just connected to the store. "
                                "Greet them warmly in one short sentence and ask what they are looking for today. ---"
                            )
                        except asyncio.CancelledError:
                            log.debug("startup_greeting_cancelled", session_id=self.session_id)
                            raise
                        except RuntimeError as exc:
                            # Session may close between scheduling and send.
                            log.info(
                                "startup_greeting_skipped_runtime",
                                session_id=self.session_id,
                                error=str(exc),
                            )
                        except Exception as exc:
                            log.warning(
                                "startup_greeting_error",
                                session_id=self.session_id,
                                error=str(exc),
                                exc_info=True,
                            )

                    self._startup_greeting_task = asyncio.create_task(
                        delayed_greeting(),
                        name=f"startup_greeting:{self.session_id}",
                    )

                # 3 ====== Run the two communication tasks concurrently until one raises an exception (e.g. disconnect) ======
                # gather() runs both loops simultaneously.
                # return_exceptions=False means if one loop crashes, the other is cancelled cleanly.
                await asyncio.gather(
                    self._browser_to_gemini_task(websocket, gemini),
                    self._gemini_to_browser_task(websocket, gemini),
                    return_exceptions=False,
                )

        except WebSocketDisconnect:
            log.info(
                "ws_disconnected_normally", session_id=self.session_id, turns=len(self._transcript)
            )

        except Exception as exc:
            log.error(
                "ws_handler_error",
                session_id=self.session_id,
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )
            try:
                await self._send_error(
                    str(exc)
                )  # Notify browser of the error so it can show a message instead of hanging.
            except Exception:
                pass  # WebSocket is already gone

        finally:
            if self._startup_greeting_task is not None and not self._startup_greeting_task.done():
                self._startup_greeting_task.cancel()
                try:
                    await self._startup_greeting_task
                except asyncio.CancelledError:
                    pass
            self._startup_greeting_task = None
            if (
                self._pending_text_flush_task is not None
                and not self._pending_text_flush_task.done()
            ):
                self._pending_text_flush_task.cancel()
                try:
                    await self._pending_text_flush_task
                except asyncio.CancelledError:
                    pass
            self._pending_text_flush_task = None
            self._gemini = None
            log.info(
                "ws_handler_finished", session_id=self.session_id, total_turns=len(self._transcript)
            )

    # =========================================================================
    # TASK A — BROWSER → GEMINI
    # =========================================================================
    async def _browser_to_gemini_task(
        self, websocket: WebSocket, gemini: GeminiLiveHandler
    ) -> None:
        """
        Continuously receives messages from the browser and forwards to Gemini.

        Handles two types of incoming frames:
            Binary frames: raw PCM audio (mic chunks) → gemini.send_audio_chunk()
            Text frames:   JSON messages with user text → gemini.send_text()
        """
        while True:
            # await websocket.receive()
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                # Browser closed the connection cleanly
                raise WebSocketDisconnect(code=message.get("code", 1000))

            # log.info("browser_message_received", message_type=message["type"], session_id=self.session_id )
            raw_bytes: bytes | None = message.get("bytes")
            raw_text: str | None = message.get("text")

            # ── 1. HANDLE AUDIO (Microphone) ──────────────────────────────
            if raw_bytes:
                self._user_started_interaction = True
                if self._input_mode == "text":
                    self._input_mode = "audio"
                    log.info("input_mode_switched_to_audio", session_id=self.session_id)

                # Skip tiny chunks (browser may send near-silence)
                if len(raw_bytes) < 32:
                    log.info(
                        "send audio chunk from browser skipped", bytes=len(raw_bytes)
                    )  # for test  as temp
                    continue

                log.debug(
                    "mic_chunk_received", bytes=len(raw_bytes), session_id=self.session_id
                )  # for test as temp
                # Stream the raw binary straight into Google's ears
                if gemini.is_connected:
                    await gemini.send_audio_chunk(raw_bytes)
                else:
                    log.debug(
                        "audio_chunk_skipped_gemini_not_connected", session_id=self.session_id
                    )

            # ── 2. HANDLE TEXT (Chat Box) TEXT FRAME = typed message or control JSON ─────────────
            elif raw_text is not None:
                # ── TEXT FRAME = typed message or control JSON ─────────────
                # try:
                #     parsed = json.loads(raw_text)
                # except json.JSONDecodeError:
                #     parsed = None

                # # control message from browser: user stopped speaking
                # if isinstance(parsed, dict) and parsed.get("type") == MSG_AUDIO_END:
                #     log.info("audio_end_received_from_browser", session_id=self.session_id)
                #     await gemini.send_audio_stream_end()
                #     await self._send_status(STATUS_THINKING, "Processing speech...")
                #     continue

                # ── 2.1 HANDLE CONTEXT UPDATES (Hidden from Chat) ─────────────
                try:
                    parsed = json.loads(raw_text)
                    if isinstance(parsed, dict) and parsed.get("type") == "cart_sync":
                        page = parsed.get("page", {})
                        cart_items = parsed.get("cart_items", [])
                        cart_tools.sync_cart_from_browser(self.session_id, cart_items)
                        if checkout_tools.invalidate_checkout_if_cart_changed(
                            self.session_id, cart_items
                        ):
                            await self._send_json({"type": "action", "action": "close_checkout"})

                        await gemini.inject_live_context(
                            page=page,
                            products=parsed.get("products", []),
                        )

                        if parsed.get("announce_to_ai") and parsed.get("product_id"):
                            if gemini.is_connected:
                                await gemini.send_text(
                                    "--- SYSTEM: The user added an item to the cart using the page UI. "
                                    f"Product ID {parsed.get('product_id')} is already in the cart. "
                                    "Briefly confirm it in one short sentence. Do not call add_to_cart. "
                                    "Do not ask whether they want to add it. ---"
                                )
                        continue

                    if isinstance(parsed, dict) and parsed.get("type") == "context_update":
                        page = parsed.get("page", {})
                        if "cart_items" in page:
                            cart_tools.sync_cart_from_browser(
                                self.session_id, page.get("cart_items", [])
                            )
                            if checkout_tools.invalidate_checkout_if_cart_changed(
                                self.session_id, page.get("cart_items", [])
                            ):
                                await self._send_json(
                                    {"type": "action", "action": "close_checkout"}
                                )
                        log.info(
                            "context_update_received",
                            session_id=self.session_id,
                            filter_count=len(parsed.get("page", {}).get("active_filters", [])),
                            items=len(parsed.get("products", [])),
                            cart_count=parsed.get("page", {}).get("cart_count", 0),
                        )
                        if self._payload_logging_enabled():
                            log.debug("context_update_payload", parsed=parsed)
                        await gemini.inject_live_context(
                            page=parsed.get("page", {}), products=parsed.get("products", [])
                        )
                        continue  # Skip the rest of the loop so it doesn't show in chat!
                except json.JSONDecodeError:
                    pass

                # ── TEXT FRAME = typed message or control JSON ─────────────
                user_text = self._parse_text_message(raw_text)

                if not user_text.strip():
                    continue

                self._user_started_interaction = True
                self._input_mode = "text"
                log.info(
                    "text_message_received",
                    session_id=self.session_id,
                    text_length=len(user_text),
                )

                # Save to memory transcript (used later for UI and DB saving)
                self._transcript.append({"role": "user", "text": user_text})
                # Signal browser: AI is processing
                await self._send_status(STATUS_THINKING)

                sent_immediately = await self._queue_or_send_user_text(user_text, gemini)
                if not sent_immediately:
                    await self._send_status(STATUS_THINKING, "Connecting to AI session...")

    async def _gemini_to_browser_task(
        self, websocket: WebSocket, gemini: GeminiLiveHandler
    ) -> None:
        """
        Task B: Receives events from Gemini and forwards them to the browser.

        WHY A SEPARATE TASK:
            In voice mode, Gemini's response can start arriving WHILE the user is
            still speaking. A serial (one-after-another) approach would buffer
            everything and create massive lag. As a separate task, we can stream
            audio down to the browser the millisecond Google generates it.

        THE RECEIVE LOOP:
            `gemini.receive_events()` yields a continuous stream of dictionaries.
            We stay in this `async for` loop for the entire conversation.
        """
        ai_transcript_parts: list[str] = []
        user_transcript_parts: list[str] = []
        async for event in gemini.receive_events():
            event_type = event.get("type")

            # ── 1. AUDIO CHUNK (The AI speaking) ──────────────────────────
            if event_type == MSG_AUDIO:
                audio_bytes: bytes = event["data"]

                # Stream the raw audio bytes directly to the browser speakers
                if audio_processor.is_valid_audio_chunk(audio_bytes):
                    await websocket.send_bytes(audio_bytes)

            # ──2 OUTPUT TRANSCRIPT (Text of what Gemini SAID) ──────────────────────
            elif event_type == "output_transcript":
                cleaned_output_text = self._sanitize_display_text(event["text"])
                if "[SILENT_UPDATE]" in event["text"]:
                    log.info(
                        "output_transcript_silent_update",
                        session_id=self.session_id,
                        text_length=len(event["text"]),
                    )
                    continue
                if not cleaned_output_text:
                    continue

                ai_transcript_text = cleaned_output_text
                ai_transcript_parts.append(ai_transcript_text)

                # Send the growing transcript to the browser (for live captioning)
                await self._send_json(
                    {"type": MSG_TRANSCRIPT, "role": "ai", "text": ai_transcript_text}
                )

            # ── 3. INPUT TRANSCRIPT (Text of what the User said in audio mode) ──────────
            elif event_type == "input_transcript" and self._input_mode == "audio":
                user_transcript_text = self._sanitize_display_text(event["text"])
                if not user_transcript_text:
                    continue
                log.info(
                    "user_speech_transcribed",
                    session_id=self.session_id,
                    text_length=len(user_transcript_text),
                )
                user_transcript_parts.append(user_transcript_text)
                # Send the growing transcript to the browser (for live captioning)
                await self._send_json(
                    {"type": MSG_TRANSCRIPT, "role": "user", "text": user_transcript_text}
                )

            # ── 4. TEXT CHUNK (rare in audio mode) ───────────────────────────
            elif event_type == MSG_TEXT:
                cleaned_text = self._sanitize_display_text(event["text"])
                if self._input_mode == "audio":
                    log.debug("text_chunk_skipped_audio_mode", session_id=self.session_id)
                    continue
                if not cleaned_text:
                    log.debug("text_chunk_skipped_empty_after_sanitize", session_id=self.session_id)
                    continue
                log.info(
                    "text_chunk_received",
                    session_id=self.session_id,
                    text_length=len(event["text"]),
                )
                # THE FIX: Intercept the silent acknowledgment so it doesn't show in the chat UI!
                if "[SILENT_UPDATE]" in event["text"]:
                    continue
                await self._send_json(
                    {
                        "type": MSG_TEXT,
                        "text": cleaned_text,
                    }
                )

            # ── 5. TOOL CALL ─────────────────────────────────────────────────
            elif event_type == "tool_call":
                tool_name = event.get("name", "")
                tool_args = event.get("args", {})
                call_id = event.get("call_id")
                # log.info("tool_call_received",  tool=tool_name, session=self.session_id ,call_id = call_id, args =tool_args )

                # 1. Execute the tool and get the result string AS Execute the python tool using our dispatcher (Returns our strict ToolResponse object!)
                context = tool_dispatcher.ToolContext(session_id=self.session_id)
                tool_response = await tool_dispatcher.execute(tool_name, tool_args, context)
                log.info(
                    "tool_call_result",
                    tool=tool_name,
                    session=self.session_id,
                    response_length=len(tool_response.ai_text),
                )

                # 2. TRAFFIC TO BROWSER UI
                # Send the object to the Action Dispatcher to calculate visual commands
                actions = self.action_dispatcher.dispatch(
                    tool_name=tool_name, tool_args=tool_args, tool_response=tool_response
                )

                # Send each visual command down the websocket to the user's browser
                for action in actions:
                    await self._send_json(action.model_dump())

                # 3. TRAFFIC TO GEMINI AI
                # Send the result back to Gemini, referencing the call_id so Gemini knows which call this result belongs to
                # # We format the payload as a dictionary for Gemini
                # if tool_response.status == "error":
                #     gemini_payload = {"error": tool_response.ai_text}
                # else:
                #     gemini_payload = {"result": tool_response.ai_text}
                #  temporary we will just send str not dict to gemini as im buildig the send_tool_result to take str nad send str not dict
                await gemini.send_tool_result(call_id, tool_name, tool_response.ai_text)

            # # ── 6. INTERRUPT ─────────────────────────────────────────────────
            # elif event_type == "interrupted":
            #     log.info("gemini_interrupted", session_id=self.session_id)
            #     await self._send_json({"type": "interrupted"})

            # ── 7. RESUMPTION HANDLE ──────────────────────────────────────────
            elif event_type == "resumption_handle":
                handle = event.get("handle")
                if handle is not None:
                    GLOBAL_HANDLES[self.session_id] = handle
                    log.info(
                        "resumption_handle_received", handle=handle, session_id=self.session_id
                    )
                    # Optionally send to frontend so it can be saved
                    # await self._send_json({"type": "resumption_handle", "handle": handle})

            # ── 8. TURN COMPLETE (The AI finished its thought or One complete turn) ────────────
            elif event_type == "turn_complete":
                # One AI response turn finished.
                # In voice mode: DON'T break — keep looping for the next turn.
                # Save completed transcript, reset status, re-enable UI.
                if user_transcript_parts:
                    full_user_text = "".join(user_transcript_parts)
                    self._transcript.append({"role": "user", "text": full_user_text})
                    user_transcript_parts.clear()
                    log.debug(
                        "turn_saved user_transcript",
                        length=len(full_user_text),
                        session=self.session_id,
                    )

                if ai_transcript_parts:
                    full_ai_text = "".join(ai_transcript_parts)
                    self._transcript.append({"role": "ai", "text": full_ai_text})
                    ai_transcript_parts.clear()
                    log.debug(
                        "turn_saved ai_transcript",
                        length=len(full_ai_text),
                        session=self.session_id,
                    )

                log.info(
                    "memory_turn_saved",
                    session=self.session_id,
                    total_turns=len(self._transcript),
                    user_turns=sum(1 for item in self._transcript if item["role"] == "user"),
                    ai_turns=sum(1 for item in self._transcript if item["role"] == "ai"),
                )
                # Tell the browser to unlock the text box and mic button
                await self._send_status(STATUS_DONE)

            # ── 9. SESSION MANAGEMENT & ERRORS ─────────────────────────────────────────────────
            # --- NEW: Catch Google's warning that the session is about to die! ---
            elif event_type == "go_away":
                log.info("triggering_graceful_reconnect_due_to_goaway", session=self.session_id)
                # Close the browser websocket with Code 1000 so the frontend instantly reconnects!
                await websocket.close(code=1000, reason="Gemini session refresh")
                return
            # --- NEW: Catch all closures and timeouts cleanly ---
            # ── SESSION CLOSED (Gemini ended connection gracefully) ─────────
            elif event_type == "session_closed":
                reason = event.get("reason", "unknown")
                log.info("gemini_session_closed_gracefully", reason=reason, session=self.session_id)

                # If it was a timeout, a 1008 bug, or a 1001 drop, instantly reconnect!
                if reason in ["gemini_timeout", "gemini_live_1008", "normal_closure"] or event.get(
                    "retryable"
                ):
                    await websocket.close(code=1000, reason="Gemini session refresh")
                else:
                    await websocket.close(code=1000, reason="Session closed")
                return

            # ── ERROR ─────────────────────────────────────────────────────
            elif event_type == MSG_ERROR:
                error_message: str = event.get("message", "Unknown Gemini error")
                log.error("gemini_error", error=error_message, session=self.session_id)
                await self._send_error(f"AI error: {error_message}")

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _parse_text_message(self, raw_text: str) -> str:
        """
        Extract user text from a raw WebSocket text frame.

        Accepts both:
          Plain string:  "show me shoes"
          JSON object:   {"type": "text", "text": "show me shoes"}
        """
        try:
            parsed_data = json.loads(raw_text)
            if isinstance(parsed_data, dict):
                user_text = parsed_data.get("text", "")
                log.debug("text_message_parsed_as_json", text_length=len(user_text))
                return user_text
            if isinstance(parsed_data, str):
                log.debug("text_message_parsed_as_plain_string", text_length=len(parsed_data))
                return parsed_data
        except (json.JSONDecodeError, ValueError):
            pass
        return raw_text

    async def _send_json(self, payload: dict) -> None:
        """Helper to send JSON messages to the browser."""
        if self._websocket:
            await self._websocket.send_text(json.dumps(payload))

    async def _send_status(self, status: str, message: str = "") -> None:
        """Helper to send status messages to the browser."""
        payload: dict[str, Any] = {"type": MSG_STATUS, "status": status}
        if message:
            payload["message"] = message
        await self._send_json(payload)

    async def _send_error(self, message: str) -> None:
        """Helper to send error messages to the browser."""
        await self._send_json({"type": MSG_ERROR, "message": message})
