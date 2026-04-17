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
import time
import json
from typing import Any
import asyncio

import structlog
from fastapi import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from voice_commerce.core.voice.gemini_live_handler import GeminiLiveHandler 
from voice_commerce.core.voice  import audio_processor 
from voice_commerce.core.voice.trace_logger import trace_event
from voice_commerce.core.tools import tool_dispatcher
from voice_commerce.core.actions.action_dispatcher import ActionDispatcher
from voice_commerce.models.screen_context import get_screen_cache

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Protocol constants — all WebSocket message type strings in one place
# ---------------------------------------------------------------------------
MSG_TEXT        = "text"
MSG_AUDIO       = "audio"
MSG_TRANSCRIPT  = "transcript"
MSG_ACTION      = "action"
MSG_STATUS      = "status"
MSG_ERROR       = "error"
MSG_AUDIO_CFG   = "audio_config"
MSG_MIC_CONFIG  = "mic_config"   #  Tells browser what sample rate to capture mic at
MSG_AUDIO_END   = "audio_end"

STATUS_THINKING   = "thinking"
STATUS_RESPONDING = "responding"
STATUS_DONE       = "done"
STATUS_READY      = "ready"
STATUS_ERROR      = "error"

# GLOBAL MEMORY STORE: Keeps transcripts alive across page reloads!
# In a real production app, this would be a database like Redis or Postgres.
GLOBAL_SESSIONS: dict[str, list[dict[str, str]]] = {}
GLOBAL_HANDLES: dict[str, str] = {}  # Stores Google's resumption handles
GLOBAL_GREETING_SENT: dict[str, bool] = {}  # Persistent "welcome already sent" flag per session
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

        self.session_id = session_id or f"sess_{int(time.time() * 1000)}"
        # Fetch old memory from the global store, or start a new list if it's a new session
        if self.session_id not in GLOBAL_SESSIONS:
            GLOBAL_SESSIONS[self.session_id] = []
        self._transcript: list[dict[str, str]] = GLOBAL_SESSIONS[self.session_id]
        self._resumption_handle: str | None = GLOBAL_HANDLES.get(self.session_id)
        self._websocket: WebSocket | None = None
        self._gemini: GeminiLiveHandler | None = None
        self._input_mode: str = "text"
        self._sent_meaningful_audio_this_turn = False
        self._user_started_interaction = False
        self._assistant_turn_active = False
        self._mic_turn_stats = self._new_mic_turn_stats()
        self._gemini_turn_stats = self._new_gemini_turn_stats()
        self._startup_greeting_sent = GLOBAL_GREETING_SENT.get(
            self.session_id,
            any(turn.get("role") == "ai" for turn in self._transcript),
        )
        self.action_dispatcher = ActionDispatcher()
        log.info("voice_handler_created", session_id=self.session_id)

    def _new_mic_turn_stats(self) -> dict[str, Any]:
        return {
            "first_chunk_at": None,
            "last_chunk_at": None,
            "last_forwarded_at": None,
            "forwarded_chunks": 0,
            "ignored_chunks": 0,
            "ignored_reasons": {},
            "rms_sum": 0,
            "rms_count": 0,
            "max_rms": 0,
        }

    def _new_gemini_turn_stats(self) -> dict[str, Any]:
        return {
            "had_input_transcript": False,
            "had_model_turn_text": False,
            "had_thought_text": False,
            "had_tool_call": False,
            "had_output_transcript": False,
            "had_audio_output": False,
            "had_generation_complete": False,
        }

    def _reset_mic_turn_stats(self) -> None:
        self._mic_turn_stats = self._new_mic_turn_stats()

    def _reset_gemini_turn_stats(self) -> None:
        self._gemini_turn_stats = self._new_gemini_turn_stats()

    def _mark_assistant_turn_active(self, reason: str) -> None:
        if not self._assistant_turn_active:
            trace_event(
                self.session_id,
                "backend",
                "assistant_turn_started",
                reason=reason,
            )
        self._assistant_turn_active = True

    def _clear_assistant_turn_active(self, reason: str) -> None:
        if self._assistant_turn_active:
            trace_event(
                self.session_id,
                "backend",
                "assistant_turn_finished",
                reason=reason,
            )
        self._assistant_turn_active = False

    def _record_mic_chunk(self, *, forwarded: bool, reason: str, rms: int) -> None:
        now = time.time()
        stats = self._mic_turn_stats
        if stats["first_chunk_at"] is None:
            stats["first_chunk_at"] = now
        stats["last_chunk_at"] = now

        if forwarded:
            stats["forwarded_chunks"] += 1
            stats["last_forwarded_at"] = now
            stats["rms_sum"] += rms
            stats["rms_count"] += 1
            stats["max_rms"] = max(stats["max_rms"], rms)
            return

        stats["ignored_chunks"] += 1
        ignored_reasons = stats["ignored_reasons"]
        ignored_reasons[reason] = ignored_reasons.get(reason, 0) + 1

    def _emit_mic_turn_summary(self, trigger: str, audio_end_sent_to_gemini: bool) -> None:
        stats = self._mic_turn_stats
        if stats["first_chunk_at"] is None:
            return

        last_forwarded_at = stats["last_forwarded_at"]
        last_chunk_at = stats["last_chunk_at"]
        duration_ms = 0
        if stats["first_chunk_at"] is not None and last_chunk_at is not None:
            duration_ms = int((last_chunk_at - stats["first_chunk_at"]) * 1000)

        ms_since_last_forwarded_chunk = None
        if last_forwarded_at is not None:
            reference_ts = last_chunk_at if last_chunk_at is not None else time.time()
            ms_since_last_forwarded_chunk = int((reference_ts - last_forwarded_at) * 1000)

        avg_rms = 0
        if stats["rms_count"]:
            avg_rms = round(stats["rms_sum"] / stats["rms_count"], 2)

        trace_event(
            self.session_id,
            "backend",
            "mic_turn_summary",
            trigger=trigger,
            audio_end_sent_to_gemini=audio_end_sent_to_gemini,
            had_meaningful_audio=stats["forwarded_chunks"] > 0,
            forwarded_chunks=stats["forwarded_chunks"],
            ignored_chunks=stats["ignored_chunks"],
            ignored_reasons=dict(stats["ignored_reasons"]),
            avg_rms=avg_rms,
            max_rms=stats["max_rms"],
            duration_ms=duration_ms,
            ms_since_last_forwarded_chunk=ms_since_last_forwarded_chunk,
        )
        self._reset_mic_turn_stats()

    def _emit_gemini_turn_summary(
        self,
        *,
        user_text: str,
        ai_text: str,
        had_user_transcript: bool,
        had_ai_transcript: bool,
    ) -> None:
        stats = self._gemini_turn_stats
        if not any(stats.values()) and not had_user_transcript and not had_ai_transcript:
            return

        if stats["had_input_transcript"] and not (
            stats["had_output_transcript"]
            or stats["had_audio_output"]
            or stats["had_tool_call"]
        ):
            outcome = "silent_after_transcript"
        elif stats["had_output_transcript"] or stats["had_audio_output"]:
            outcome = "answered"
        elif stats["had_tool_call"]:
            outcome = "tool_only"
        else:
            outcome = "empty_turn"

        trace_event(
            self.session_id,
            "backend",
            "gemini_turn_summary",
            outcome=outcome,
            had_input_transcript=stats["had_input_transcript"] or had_user_transcript,
            had_model_turn_text=stats["had_model_turn_text"],
            had_thought_text=stats["had_thought_text"],
            had_tool_call=stats["had_tool_call"],
            had_output_transcript=stats["had_output_transcript"] or had_ai_transcript,
            had_audio_output=stats["had_audio_output"],
            had_generation_complete=stats["had_generation_complete"],
            user_preview=user_text[:120],
            ai_preview=ai_text[:120],
        )
        self._reset_gemini_turn_stats()


    async def handle(self, websocket: WebSocket) -> None:
        """
        The main entry point for a WebSocket connection.
        Sets up the configs of the WebSocket, opens Gemini, and runs the two communication loops.
        """
        #  ====== Accept the WebSocket connection and save the reference for later use in helper methods.======
        await websocket.accept()
        self._websocket = websocket

        log.info("ws_connected", session_id=self.session_id, client=str(websocket.client))    
        trace_event(
            self.session_id,
            "backend",
            "ws_connected",
            client=str(websocket.client),
        )

        # 1  ====== INITIAL SETUP: Send configs and open Gemini session ======
        ##  Send audio output config so browser creates AudioContext at 24kHz
        await self._send_json({"type": MSG_AUDIO_CFG, **audio_processor.get_browser_audio_config()})
        
        ##  Send microphone capture config so browser knows what rate to capture
        await self._send_json({"type": MSG_MIC_CONFIG,**audio_processor.get_mic_audio_config()})

        await self._send_status(STATUS_THINKING, "Opening AI session...")


        try:
            # 2 ====== Open the Gemini Live session ======
            async with GeminiLiveHandler(transcript=self._transcript , resumption_handle=self._resumption_handle) as gemini:
                self._gemini = gemini
                await self._send_status(STATUS_READY, "Ready — speak or type")

                # ── 2.1 Proactive Greeting (Only on first connection) ──────────
                if not self._resumption_handle and len(self._transcript) == 0:
                    async def delayed_greeting():
                        await asyncio.sleep(1.5) 
                        if self._user_started_interaction:
                            log.info("startup_greeting_skipped_user_already_active", session_id=self.session_id)
                            return
                        if self._startup_greeting_sent:
                            return
                        self._startup_greeting_sent = True
                        GLOBAL_GREETING_SENT[self.session_id] = True
                        log.info("triggering_proactive_greeting", session_id=self.session_id)
                        await gemini.send_text("SYSTEM_EVENT: GREET_USER")
                    asyncio.create_task(delayed_greeting())

                # # ── 2.2 Session Rotation (Auto-disconnect after 9 minutes of silence) ──────────
                # async def _session_timer():
                #     await asyncio.sleep(540) # 9 minutes
                #     log.info("session_9_minute_rotation_triggered", session_id=self.session_id)
                #     # Tell the widget to reconnect instantly. Because we saved the handle,
                #     # it will wake up with perfect memory!
                #     await websocket.close(code=1000, reason="Gemini session refresh")
                
                # timer_task = asyncio.create_task(_session_timer())
                # 3 ====== Run the two communication tasks concurrently until one raises an exception (e.g. disconnect) ======
                # gather() runs both loops simultaneously.
                # return_exceptions=False means if one loop crashes, the other is cancelled cleanly.
                await asyncio.gather(
                    self._browser_to_gemini_task(websocket, gemini),
                    self._gemini_to_browser_task(websocket, gemini),
                    return_exceptions=False,  

                )

        except WebSocketDisconnect:
            log.info("ws_disconnected_normally", session_id=self.session_id,
                     turns=len(self._transcript))
            trace_event(
                self.session_id,
                "backend",
                "ws_disconnected_normally",
                turns=len(self._transcript),
            )
 
        except Exception as exc:
                log.error("ws_handler_error", session_id=self.session_id,
                        error=str(exc), error_type=type(exc).__name__, exc_info=True)
                trace_event(
                    self.session_id,
                    "backend",
                    "ws_handler_error",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                try:
                    await self._send_error(str(exc)) # Notify browser of the error so it can show a message instead of hanging.
                except Exception:
                    pass  # WebSocket is already gone

        finally:
            self._gemini = None
            log.info("ws_handler_finished", session_id=self.session_id,total_turns=len(self._transcript))
            trace_event(
                self.session_id,
                "backend",
                "ws_handler_finished",
                total_turns=len(self._transcript),
            )


    # =========================================================================
    # TASK A — BROWSER → GEMINI
    # =========================================================================
    async def _browser_to_gemini_task(self ,websocket: WebSocket,gemini: GeminiLiveHandler) -> None:
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
            raw_text:  str   | None = message.get("text")

            # ── 1. HANDLE AUDIO (Microphone) ──────────────────────────────
            if raw_bytes :
                self._user_started_interaction = True
                if self._input_mode == "text":
                    self._input_mode = "audio"
                    self._sent_meaningful_audio_this_turn = False
                    self._reset_mic_turn_stats()
                    log.info("input_mode_switched_to_audio",session_id=self.session_id)

                chunk_info = audio_processor.inspect_mic_chunk(raw_bytes)
                if not chunk_info["meaningful"]:
                    self._record_mic_chunk(
                        forwarded=False,
                        reason=str(chunk_info["reason"]),
                        rms=int(chunk_info["rms"]),
                    )
                    log.debug(
                        "mic_chunk_ignored",
                        bytes=len(raw_bytes),
                        rms=chunk_info["rms"],
                        reason=chunk_info["reason"],
                        threshold=audio_processor.MIC_SILENCE_RMS_THRESHOLD,
                        session_id=self.session_id,
                    )
                    trace_event(
                        self.session_id,
                        "backend",
                        "mic_chunk_ignored",
                        bytes=len(raw_bytes),
                        rms=chunk_info["rms"],
                        reason=chunk_info["reason"],
                        threshold=audio_processor.MIC_SILENCE_RMS_THRESHOLD,
                    )
                    continue

                log.debug("mic_chunk_received",bytes=len(raw_bytes),session_id=self.session_id) # for test as temp
                self._record_mic_chunk(
                    forwarded=True,
                    reason="ok",
                    rms=int(chunk_info["rms"]),
                )
                trace_event(
                    self.session_id,
                    "backend",
                    "mic_chunk_forwarded",
                    bytes=len(raw_bytes),
                    rms=chunk_info["rms"],
                )
                # Stream the raw binary straight into Google's ears
                try:
                    await gemini.send_audio_chunk(raw_bytes)
                    self._sent_meaningful_audio_this_turn = True
                except ConnectionClosed as exc:
                    # Gemini session was already closed (for example: upstream 1008 policy close).
                    # Exit the browser->gemini loop quietly; reconnect is handled by the other task.
                    log.info(
                        "browser_to_gemini_stopping_on_closed_session",
                        session_id=self.session_id,
                        error=str(exc),
                    )
                    return


            # ── 2. HANDLE TEXT (Chat Box) TEXT FRAME = typed message or control JSON ─────────────
            elif raw_text is not None:
                try:
                    parsed = json.loads(raw_text)
                except json.JSONDecodeError:
                    parsed = None

                if isinstance(parsed, dict):
                    msg_type = parsed.get("type")

                    if msg_type == "client_trace":
                        payload = dict(parsed.get("payload", {}) or {})
                        widget_session_id = payload.pop("session_id", None)
                        payload.pop("source", None)
                        payload.pop("event", None)
                        payload.pop("run_id", None)
                        trace_event(
                            self.session_id,
                            "widget",
                            parsed.get("event", "client_trace"),
                            widget_session_id=widget_session_id,
                            **payload,
                        )
                        continue

                    # ── 2.0 Browser signals end of mic recording ─────────────
                    if msg_type == MSG_AUDIO_END:
                        trace_event(
                            self.session_id,
                            "backend",
                            "audio_end_received_from_browser",
                            forwarded_chunks_this_turn=self._mic_turn_stats["forwarded_chunks"],
                        )
                        if self._input_mode == "audio" and self._sent_meaningful_audio_this_turn:
                            log.info("audio_end_received_from_browser", session_id=self.session_id)
                            try:
                                await gemini.send_audio_stream_end()
                                trace_event(
                                    self.session_id,
                                    "backend",
                                    "audio_end_sent_to_gemini",
                                    forwarded_chunks_this_turn=self._mic_turn_stats["forwarded_chunks"],
                                )
                            except ConnectionClosed as exc:
                                log.info(
                                    "audio_end_ignored_closed_session",
                                    session_id=self.session_id,
                                    error=str(exc),
                                )
                                return
                            finally:
                                self._emit_mic_turn_summary(
                                    trigger="audio_end",
                                    audio_end_sent_to_gemini=True,
                                )
                                self._sent_meaningful_audio_this_turn = False
                        else:
                            log.debug(
                                "audio_end_ignored_not_meaningful",
                                session_id=self.session_id,
                                input_mode=self._input_mode,
                                sent_meaningful_audio=self._sent_meaningful_audio_this_turn,
                            )
                            trace_event(
                                self.session_id,
                                "backend",
                                "audio_end_ignored_not_meaningful",
                                input_mode=self._input_mode,
                                sent_meaningful_audio=self._sent_meaningful_audio_this_turn,
                            )
                            self._emit_mic_turn_summary(
                                trigger="audio_end_ignored",
                                audio_end_sent_to_gemini=False,
                            )
                        # await self._send_status(STATUS_THINKING, "Processing speech...")
                        continue

                    # ── 2.1 Silent page context update ───────────────────────
                    if msg_type == "context_update":
                        page = parsed.get("page", {}) or {}
                        products = parsed.get("products", []) or []
                        cache = get_screen_cache(self.session_id)
                        cache.update(page, products)
                        log.info(
                            "context_update_received",
                            session_id=self.session_id,
                            filters=page.get("active_filters", []),
                            items=len(products),
                            version=cache.snapshot().get("version"),
                        )
                        trace_event(
                            self.session_id,
                            "backend",
                            "context_update_received",
                            filters=page.get("active_filters", []),
                            items=len(products),
                            version=cache.snapshot().get("version"),
                            url=page.get("url", ""),
                        )
                        continue  # Skip the rest of the loop so it doesn't show in chat!

                # ── TEXT FRAME = typed message or control JSON ─────────────
                user_text = self._parse_text_message(raw_text)

                if not user_text.strip():
                    continue

                self._user_started_interaction = True
                self._input_mode = "text"
                self._sent_meaningful_audio_this_turn = False
                self._emit_mic_turn_summary(
                    trigger="text_input_switch",
                    audio_end_sent_to_gemini=False,
                )
                log.info("text_message_received",preview=user_text[:80], session_id=self.session_id)
                trace_event(
                    self.session_id,
                    "backend",
                    "text_message_received",
                    preview=user_text[:80],
                    length=len(user_text),
                )

                # Save to memory transcript (used later for UI and DB saving)
                self._transcript.append({"role": "user", "text": user_text})
                # Signal browser: AI is processing
                await self._send_status(STATUS_THINKING)

                # Send the text to Google
                try:
                    await gemini.send_text(user_text)
                except ConnectionClosed as exc:
                    log.info(
                        "text_send_ignored_closed_session",
                        session_id=self.session_id,
                        error=str(exc),
                    )
                    return

            

    async def _gemini_to_browser_task(self,websocket: WebSocket, gemini: GeminiLiveHandler) -> None:
               
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
                self._mark_assistant_turn_active("audio_output")
                self._gemini_turn_stats["had_audio_output"] = True

                # Stream the raw audio bytes directly to the browser speakers
                if audio_processor.is_valid_audio_chunk(audio_bytes):
                    await websocket.send_bytes(audio_bytes)

            # ──2 OUTPUT TRANSCRIPT (Text of what Gemini SAID) ──────────────────────
            elif event_type == "output_transcript":
                ai_transcript_text: str = event["text"]
                self._mark_assistant_turn_active("output_transcript")
                self._gemini_turn_stats["had_output_transcript"] = True
                ai_transcript_parts.append(ai_transcript_text)

                # Send the growing transcript to the browser (for live captioning)
                await self._send_json({
                    "type": MSG_TRANSCRIPT,
                    "role": "ai",
                    "text": ai_transcript_text
                })

            # ── 3. INPUT TRANSCRIPT (Text of what the User said in audio mode) ──────────
            elif event_type == "input_transcript" and  self._input_mode == "audio": 
                user_transcript_text: str = event["text"]
                self._gemini_turn_stats["had_input_transcript"] = True
                log.info("user_speech_transcribed",text=user_transcript_text[:80],session_id=self.session_id)
                user_transcript_parts.append(user_transcript_text)
                # Send the growing transcript to the browser (for live captioning)
                await self._send_json({
                    "type": MSG_TRANSCRIPT,
                    "role": "user",
                    "text": user_transcript_text
                })

            # ── 4. TEXT CHUNK (rare in audio mode) ───────────────────────────
            elif event_type == MSG_TEXT:
                self._mark_assistant_turn_active("text_output")
                self._gemini_turn_stats["had_model_turn_text"] = True
                log.info("text_chunk_received",text=event["text"],session_id=self.session_id)
                await self._send_json({
                    "type": MSG_TEXT,
                    "text": event["text"],
                })

            elif event_type == "model_turn_text":
                self._mark_assistant_turn_active("model_turn_text")
                self._gemini_turn_stats["had_model_turn_text"] = True
                if event.get("thought"):
                    self._gemini_turn_stats["had_thought_text"] = True

            # ── 5. TOOL CALL ─────────────────────────────────────────────────
            elif event_type == "tool_call":
                self._mark_assistant_turn_active("tool_call")
                self._gemini_turn_stats["had_tool_call"] = True
                tool_name = event.get("name", "")
                tool_args  = event.get("args", {})
                call_id    = event.get("call_id")
                # log.info("tool_call_received",  tool=tool_name, session=self.session_id ,call_id = call_id, args =tool_args )

                # 1. Execute the tool and get the result string AS Execute the python tool using our dispatcher (Returns our strict ToolResponse object!)
                context = tool_dispatcher.ToolContext(session_id=self.session_id)
                tool_response = await tool_dispatcher.execute(tool_name, tool_args, context)
                log.info("tool_call_result", tool=tool_name,preview=tool_response.ai_text[:100], session=self.session_id)
                
                # 2. TRAFFIC TO BROWSER UI
                # Send the object to the Action Dispatcher to calculate visual commands
                actions = self.action_dispatcher.dispatch(tool_name=tool_name, tool_args=tool_args, tool_response=tool_response)

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

            elif event_type == "generation_complete":
                self._mark_assistant_turn_active("generation_complete")
                self._gemini_turn_stats["had_generation_complete"] = True


            # # ── 6. INTERRUPT ─────────────────────────────────────────────────
            # elif event_type == "interrupted":
            #     log.info("gemini_interrupted", session_id=self.session_id)
            #     await self._send_json({"type": "interrupted"})

            # ── 7. RESUMPTION HANDLE ──────────────────────────────────────────
            elif event_type == "resumption_handle":
                handle = event.get("handle")
                if handle is not None:
                    GLOBAL_HANDLES[self.session_id] = handle
                    log.info("resumption_handle_received", handle=handle, session_id=self.session_id)
                    # Optionally send to frontend so it can be saved
                    # await self._send_json({"type": "resumption_handle", "handle": handle})

            # ── 8. TURN COMPLETE (The AI finished its thought or One complete turn) ────────────
            elif event_type == "turn_complete":
                self._clear_assistant_turn_active("turn_complete")
                self._sent_meaningful_audio_this_turn = False
                # One AI response turn finished.
                # In voice mode: DON'T break — keep looping for the next turn.
                # Save completed transcript, reset status, re-enable UI.
                full_user_text = ""
                if user_transcript_parts:
                    full_user_text = "".join(user_transcript_parts)
                    self._transcript.append({"role": "user", "text": full_user_text})
                    user_transcript_parts.clear()
                    log.debug("turn_saved user_transcript", length=len(full_user_text),session=self.session_id)
                
                full_ai_text = ""
                if ai_transcript_parts :
                    full_ai_text = "".join(ai_transcript_parts)
                    self._transcript.append({"role": "ai", "text": full_ai_text})
                    ai_transcript_parts.clear()
                    log.debug("turn_saved ai_transcript", length=len(full_ai_text),session=self.session_id)

                self._emit_gemini_turn_summary(
                    user_text=full_user_text,
                    ai_text=full_ai_text,
                    had_user_transcript=bool(full_user_text),
                    had_ai_transcript=bool(full_ai_text),
                )
                log.info("memory", memory=self._transcript)
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
                self._clear_assistant_turn_active(f"session_closed:{reason}")
                self._emit_gemini_turn_summary(
                    user_text="".join(user_transcript_parts),
                    ai_text="".join(ai_transcript_parts),
                    had_user_transcript=bool(user_transcript_parts),
                    had_ai_transcript=bool(ai_transcript_parts),
                )
                log.info("gemini_session_closed_gracefully", reason=reason, session=self.session_id)
                
                # If it was a timeout, a 1008 bug, or a 1001 drop, instantly reconnect!
                if reason in ["gemini_timeout", "gemini_live_1008", "normal_closure"] or event.get("retryable"):
                    await websocket.close(code=1000, reason="Gemini session refresh")
                else:
                    await websocket.close(code=1000, reason="Session closed")
                return
            
            # ── ERROR ─────────────────────────────────────────────────────
            elif event_type == MSG_ERROR:
                error_message: str = event.get("message", "Unknown Gemini error")
                log.error("gemini_error",  error=error_message, session=self.session_id)
                await self._send_error(f"AI error: {error_message}")
                



        
        

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _parse_text_message(self,raw_text: str) -> str:
        """
        Extract user text from a raw WebSocket text frame.
 
        Accepts both:
          Plain string:  "show me shoes"
          JSON object:   {"type": "text", "text": "show me shoes"}
        """
        try:
            parsed_data = json.loads(raw_text)
            if isinstance(parsed_data, dict) :
                user_text = parsed_data.get("text", "")
                log.debug("text_message_parsed_as_json", text=user_text[:80])
                return user_text
            if isinstance(parsed_data, str):
                log.debug("text_message_parsed_as_plain_string", text=parsed_data[:80])
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
        payload : dict[str , Any] = {"type": MSG_STATUS, "status": status}
        if message:
            payload["message"] = message
        await self._send_json(payload)
        

    async def _send_error(self, message: str) -> None:
        """Helper to send error messages to the browser."""
        await self._send_json({"type": MSG_ERROR, "message": message})
        
