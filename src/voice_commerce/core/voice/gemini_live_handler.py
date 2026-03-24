from __future__ import annotations
from  collections.abc import AsyncGenerator
from typing import Any


import structlog
from google import genai
from google.genai import types

from voice_commerce.core.tools import tool_registry   # ← Phase 3: import the tool declarations
from voice_commerce.core.voice import audio_processor  # ← Phase 5: import audio config for browser
from voice_commerce.config.settings import settings


log = structlog.get_logger(__name__)


class GeminiLiveHandler:

    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key) 
        self._session: Any = None
        self._session_ctx: Any = None   
        self._config = self._build_session_config()

        log.debug(
            "gemini_live_handler_created",
            model=settings.gemini_model,
            voice=settings.gemini_voice_name,
        )

    def _build_session_config(self) -> types.LiveConnectConfig:
        """Builds the configuration for the Gemini speech session."""
        

        return types.LiveConnectConfig(

            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(
                parts=[
                    types.Part(
                        text=self._build_system_prompt()
                    )
                ]
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=settings.gemini_voice_name
                        # Available: "Aoede", "Charon", "Fenrir", "Kore", "Puck"
                        # Charon: clear, neutral — good for shopping assistant
                    )
                )
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),   
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=tool_registry.get_all_tools(),   # ← Phase 3: the one new line

            )
            

    
    def _build_system_prompt(self) -> str:
        """The 'Rules' the AI must follow."""
        return (
            "You are a friendly Voice Shopping Assistant. "
            "ALWAYS respond in English only, regardless of the language the user speaks. "
            "Keep answers short and conversational — 1 to 3 sentences maximum. "
            "If you don't understand the user, ask one short clarifying question."
        )
    

    async def send_text(self, text: str) -> None:
        """Sends text to Gemini and yields response text as it arrives."""
        if self._session is None:
            raise RuntimeError(
                "Cannot send text: Gemini session is not connected. "
                "Did you use 'async with handler.connect():'?"
            )
        
        log.debug("gemini_sending_text", text=text)

        await self._session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=text)]
            ),
            turn_complete=True,
            # turn_complete=True is the key flag that tells Gemini:
            # "The user is done speaking, please respond now."
        )



    async def send_audio_chunk(self, pcm_bytes: bytes) -> None:
        """
        Stream mic audio from the browser to Gemini.
        Added in Phase 5 (microphone input). Kept here ready for that phase.
 
        Format required: PCM s16le at 16kHz mono.
        Uses send_realtime_input() not send_client_content() because audio is
        a continuous stream — Gemini's VAD detects speech pauses automatically.
        """
        log.debug("gemini_sending_audio_chunk", bytes=len(pcm_bytes))
        if self._session is None:
            raise RuntimeError("Cannot send audio: session not connected.")
        if not pcm_bytes:
            return  # skip empty chunks (can happen with some mic implementations)

        await self._session.send_realtime_input(
            audio=types.Blob(
                data=pcm_bytes,
                mime_type=f"audio/pcm;rate={audio_processor.MIC_SAMPLE_RATE}",
            )
        )


    async def send_tool_result(self, call_id:   str | None, tool_name: str,result:    str) -> None:

        if self._session is None:
            raise RuntimeError("Cannot send tool result: not connected.")
        log.debug("gemini_sending_tool_result",tool=tool_name, preview=result[:80])

        await self._session.send_tool_response(
            function_responses=[
                types.FunctionResponse(
                    id=call_id,  # correlate with the tool call
                    name=tool_name,
                    response={"result": result},
                )
            ],
        )

            # """
            # Send a tool's return value back to Gemini after executing it.  ← new Phase 3
 
            # FULL FLOW:
            # 1. User:  "show me running shoes"
            # 2. Gemini yields tool_call → name="search_products", args={"query":"running shoes"}
            # 3. Handler dispatches → search_products() runs → returns result string
            # 4. Handler calls this method → result delivered to Gemini
            # 5. Gemini reads result → speaks it naturally to the user
    
            # WHY send_tool_response() NOT send_client_content():
            # send_client_content() is for USER messages (text or audio the user sent).
            # send_tool_response() is for FUNCTION RESULTS.
            # The Gemini API routes them to completely different internal processors.
            # Using send_client_content() here would make Gemini treat your search
            # results as if the USER said them — broken conversation structure.
    
            # WHY result is a string (not JSON or a dict):
            # Gemini reads the result as text context, then paraphrases it into
            # natural speech. A structured readable string like:
            #     "• Nike Air Zoom — $129 — ID:1\n  Lightweight running shoe."
            # is ideal. Gemini turns this into:
            #     "I found the Nike Air Zoom for a hundred and twenty-nine dollars.
            #     It's a lightweight running shoe. Want to add it to your cart?"
    
            # ABOUT call_id:
            # Gemini assigns a unique ID to each tool call for correlation.
            # It can be None for some model versions — send_tool_response handles None.
            # """

    async def receive_events(self) -> AsyncGenerator[dict[str, Any], None]:
        if self._session is None:
            raise RuntimeError("Cannot receive: Gemini session is not connected.")
        while True:
            try:
                async for response  in self._session.receive():
                    # Gemini sends text in chunks (like a typewriter)
                    response: types.LiveServerMessage
                    if response.text is not None:
                        log.debug("gemini_text_chunk", length=len(response.text))
                        yield {"type": "text", "text": response.text}

                    if response.data is not None:
                        log.debug("gemini_audio_chunk", bytes=len(response.data))
                        yield {"type": "audio", "data": response.data}
                    
                    # ── Tool call ← Phase 3 ─────────────────────────────────
                    # When Gemini decides to call a function, it sends the call
                    # in model_turn.parts (not in response.text or response.data).
                    # We detect it here and yield it so the handler can dispatch it.
                    #
                    # WHY check model_turn.parts (not just response.text):
                    #   Function calls are a separate part type in the Gemini API.
                    #   They arrive as Part objects with a function_call field,
                    #   not as text. You cannot detect them from response.text.

                    if (
                        response.server_content
                        and response.server_content.model_turn
                        and response.server_content.model_turn.parts
                    ):
                        for part in response.server_content.model_turn.parts:
                            if hasattr(part, "function_call") and part.function_call:
                                log.info("gemini_tool_call_detected",tool_name=part.function_call.name)
                                yield {
                                    "type": "tool_call",
                                    "name": part.function_call.name,
                                    "args": dict(part.function_call.args or {}),
                                    "call_id": getattr(part.function_call, "id", None),
                                }

                    # INPUT TRANSCRIPT (Phase 5+)
                    # Text version of what the USER said (from their audio)
                    if (
                        response.server_content
                        and hasattr(response.server_content, "input_transcription")
                        and response.server_content.input_transcription
                    ):
                        transcript = response.server_content.input_transcription
                        if hasattr(transcript, "text") and transcript.text:
                            log.debug("gemini_input_transcript", text=transcript.text[:80])
                            yield {"type": "input_transcript", "text": transcript.text}
    
                    # OUTPUT TRANSCRIPT (Phase 4+)
                    # Text version of what GEMINI said (from its audio response)
                    if (
                        response.server_content
                        and hasattr(response.server_content, "output_transcription")
                        and response.server_content.output_transcription
                    ):
                        transcript = response.server_content.output_transcription
                        if hasattr(transcript, "text") and transcript.text:
                            log.debug("gemini_output_transcript", text=transcript.text[:80])
                            yield {"type": "output_transcript", "text": transcript.text}

                    # Check if Gemini is finished with its thought
                    if response.server_content and response.server_content.turn_complete:
                        yield {"type": "turn_complete"}
                        break  # exit inner loop → outer loop restarts immediately
            except Exception as exc:
                error_str = str(exc)
                if "1000" in error_str or error_str.strip() in ("1000 None.", "1001 None."):
                    log.info("gemini_session_closed_by_server", reason=error_str)
                    yield {"type": "session_closed", "reason": error_str}
                    return  # Stop — session is over, browser will auto-reconnect
                # Real error — log, notify browser, stop
                log.error("gemini_receive_error", error=error_str)
                yield {"type": "error", "message": error_str}
                return


    async def __aenter__(self) -> "GeminiLiveHandler":
        log.info("gemini_session_connecting", model=settings.gemini_model   )

        self._session_ctx = self._client.aio.live.connect(
            model=settings.gemini_model,
            config=self._config,
        )

        # Enter the context manager → opens the WebSocket to Gemini's servers
        self._session = await self._session_ctx.__aenter__()
        log.info("gemini_session_connected")
        return self
    

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """ 
        Close the Gemini Live session.
        Called automatically when exiting the `async with` block.
 
        exc_type, exc_val, exc_tb: exception info if an exception occurred
        (None, None, None if the block exited normally)
        """
        log.info("gemini_session_closing")
 
        if self._session_ctx is not None:
            try:
                # Close the google-genai context manager (closes the WebSocket)
                await self._session_ctx.__aexit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                # Don't let cleanup errors mask the original exception
                log.warning("gemini_session_close_error", error=str(e))
            finally:
                self._session = None                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          
                self._session_ctx = None
 
        log.info("gemini_session_closed")