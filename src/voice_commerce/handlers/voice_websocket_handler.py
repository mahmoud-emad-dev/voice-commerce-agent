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

from voice_commerce.core.voice.gemini_live_handler import GeminiLiveHandler 
from voice_commerce.core.voice  import audio_processor 
from voice_commerce.core.tools import tool_dispatcher

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
# MSG_AUDIO_END   = "audio_end"

STATUS_THINKING   = "thinking"
STATUS_RESPONDING = "responding"
STATUS_DONE       = "done"
STATUS_READY      = "ready"
STATUS_ERROR      = "error"


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

        self._transcript: list[dict[str, str]] = []
        self._websocket: WebSocket | None = None
        self._gemini: GeminiLiveHandler | None = None
        self._input_mode: str = "text"

        log.info("voice_handler_created", session_id=self.session_id)


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
        await self._send_json({"type": MSG_MIC_CONFIG,**audio_processor.get_mic_audio_config()})

        await self._send_status(STATUS_THINKING, "Opening AI session...")


        try:
            # 2 ====== Open the Gemini Live session ======
            async with GeminiLiveHandler() as gemini:
                self._gemini = gemini
                await self._send_status(STATUS_READY, "Ready — speak or type")

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
 
        except Exception as exc:
                log.error("ws_handler_error", session_id=self.session_id,
                        error=str(exc), error_type=type(exc).__name__, exc_info=True)
                try:
                    await self._send_error(str(exc)) # Notify browser of the error so it can show a message instead of hanging.
                except Exception:
                    pass  # WebSocket is already gone

        finally:
            self._gemini = None
            log.info("ws_handler_finished", session_id=self.session_id,total_turns=len(self._transcript))


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
                if self._input_mode == "text":
                    self._input_mode = "audio"
                    log.info("input_mode_switched_to_audio",session_id=self.session_id)
                
                # Skip tiny chunks (browser may send near-silence)
                if len(raw_bytes) < 64:
                    log.info("send audio chunk from browser skipped",bytes=len(raw_bytes)) # for test  as temp
                    continue   
                
                log.debug("mic_chunk_received",bytes=len(raw_bytes),session_id=self.session_id) # for test as temp
                # Stream the raw binary straight into Google's ears
                await gemini.send_audio_chunk(raw_bytes)


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

                user_text = self._parse_text_message(raw_text)

                if not user_text.strip():
                    continue

                self._input_mode = "text"
                log.info("text_message_received",preview=user_text[:80], session_id=self.session_id)

                # Save to memory transcript (used later for UI and DB saving)
                self._transcript.append({"role": "user", "text": user_text})
                # Signal browser: AI is processing
                await self._send_status(STATUS_THINKING)

                # Send the text to Google
                await gemini.send_text(user_text)


            

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

                # Stream the raw audio bytes directly to the browser speakers
                if audio_processor.is_valid_audio_chunk(audio_bytes):
                    await websocket.send_bytes(audio_bytes)

            # ──2 OUTPUT TRANSCRIPT (Text of what Gemini SAID) ──────────────────────
            elif event_type == "output_transcript":
                ai_transcript_text: str = event["text"]
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
                await self._send_json({
                    "type": MSG_TEXT,
                    "text": event["text"],
                })

            # ── 5. TOOL CALL ─────────────────────────────────────────────────
            elif event_type == "tool_call":
                tool_name = event.get("name", "")
                tool_args  = event.get("args", {})
                call_id    = event.get("call_id")
                # log.info("tool_call_received",  tool=tool_name, session=self.session_id ,call_id = call_id, args =tool_args )

                # Execute the tool and get the result string AS Execute the python tool using our dispatcher
                context = tool_dispatcher.ToolContext(session_id=self.session_id)
                result = await tool_dispatcher.execute(tool_name, tool_args, context)
                log.info("tool_call_result", tool=tool_name,preview=result[:80], session=self.session_id)
                # Send the result back to Gemini, referencing the call_id so Gemini knows which call this result belongs to
                await gemini.send_tool_result(call_id, tool_name, result)

            # # ── 6. INTERRUPT ─────────────────────────────────────────────────
            # elif event_type == "interrupted":
            #     log.info("gemini_interrupted", session_id=self.session_id)
            #     await self._send_json({"type": "interrupted"})


            # ── 7. TURN COMPLETE (The AI finished its thought or One complete turn) ────────────
            elif event_type == "turn_complete":
                # One AI response turn finished.
                # In voice mode: DON'T break — keep looping for the next turn.
                # Save completed transcript, reset status, re-enable UI.
                if user_transcript_parts:
                    full_user_text = "".join(user_transcript_parts)
                    self._transcript.append({"role": "user", "text": full_user_text})
                    user_transcript_parts.clear()
                    log.debug("turn_saved user_transcript", length=len(full_user_text),session=self.session_id)
                
                if ai_transcript_parts :
                    full_ai_text = "".join(ai_transcript_parts)
                    self._transcript.append({"role": "ai", "text": full_ai_text})
                    ai_transcript_parts.clear()
                    log.debug("turn_saved ai_transcript", length=len(full_ai_text),session=self.session_id)
                                
                log.info("memory", memory=self._transcript)
                # Tell the browser to unlock the text box and mic button
                await self._send_status(STATUS_DONE)

            # ── 8. SESSION MANAGEMENT & ERRORS ─────────────────────────────────────────────────
            # ── SESSION CLOSED (Gemini ended connection gracefully) ─────────
            elif event_type == "session_closed":
                # Now we notify the browser so it can reconnect.
                reason = event.get("reason", "unknown")
                log.info("gemini_session_closed_gracefully",
                         reason=reason, session=self.session_id)
                await self._send_status(STATUS_ERROR, "Session ended — reconnecting...")
            
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
        
