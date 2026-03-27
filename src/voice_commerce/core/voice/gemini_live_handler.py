# src/voice_commerce/core/voice/gemini_live_handler.py
# ==============================================================================
# PURPOSE: The isolated adapter for the Google Gemini Live API.
#
# ==============================================================================

from __future__ import annotations
import asyncio
from  collections.abc import AsyncGenerator
from typing import Any


import structlog
from google import genai
from google.genai import types

from voice_commerce.core.tools import tool_registry   
from voice_commerce.core.voice import audio_processor  
from voice_commerce.config.settings import settings


log = structlog.get_logger(__name__)


class GeminiLiveHandler:
    """Handles the bidirectional audio/text stream with Gemini."""

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

    # =========================================================================
    # Gemini Configuration ( Session - Prompt - Voice - Others)
    # =========================================================================

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
                    ),
                language_code="en-US",
                ),
            input_audio_transcription=types.AudioTranscriptionConfig(),   
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=tool_registry.get_all_tools(),  
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            # realtime_input_config=types.RealtimeInputConfig(
            #         automatic_activity_detection=types.AutomaticActivityDetection(
            #             disabled=False,
            #             start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
            #             end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
            #             prefix_padding_ms=100,
            #             silence_duration_ms=600,
            #         )
                # ),

            )
            
    
    def _build_system_prompt(self) -> str:
        """The 'Rules' the AI must follow."""
        return """
                You are a friendly voice shopping assistant.

                Rules:
                - Keep answers short.
                - Wait until the user's intent is clear before calling any tool.
                - If the user utterance is partial, vague, noisy, or unfinished, ask one short clarification question.
                - Do not call tools for filler or ambiguous phrases like: "what about", "okay", ".", "yes", "no" unless the previous turn already made the target product explicit.
                - Before add_to_cart, make sure the product is explicit and the user clearly confirmed it.
                - If the user asks about the current product with vague follow-ups like "what about price?" or "describe it", keep referring to the last clearly discussed product.
                """ 

    # =========================================================================
    # SENDING METHODS (App -> Gemini)
    # =========================================================================
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
            turn_complete=True, # turn_complete=True is the key flag that tells Gemini: "The user is done speaking, please respond now."
            
        )


    async def send_audio_chunk(self, pcm_bytes: bytes) -> None:
        """
        Stream mic audio from the browser to Gemini. 
        Uses send_realtime_input() not send_client_content() because audio is
        a continuous stream — Gemini's VAD detects speech pauses automatically.
        """
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
        """
        Send a python function's return value back to Gemini after executing it.
 
        FULL FLOW:
        1. User:  "show me running shoes"
        2. Gemini yields tool_call → name="search_products"
        3. Handler dispatches → search_products() runs → returns result string
        4. Handler calls this method → result delivered to Gemini
        5. Gemini reads result → speaks it naturally to the user
 
        WHY result is a string (not JSON or a dict):
        Gemini reads the result as text context, then paraphrases it into
        natural speech. A structured readable string is ideal.
        """

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


    # async def send_audio_stream_end(self) -> None:
    #     """
    #     Tell Gemini that the current user audio stream has ended.
    #     This helps Gemini flush buffered speech and respond sooner.
    #     """
    #     if self._session is None:
    #         raise RuntimeError("Cannot end audio stream: session not connected.")

    #     await self._session.send_realtime_input(audio_stream_end=True)

    # =========================================================================
    # RECEIVING Events METHOD (Gemini -> App)
    # =========================================================================
    async def receive_events(self) -> AsyncGenerator[dict[str, Any], None]:
        """
        Listens to the stream from Gemini and yields events to the app.
        """
        if self._session is None:
            raise RuntimeError("Cannot receive: Gemini session is not connected.")
        try:
            # We need this outer loop because session.receive() naturally ends 
            # its iterator after a turn completes. This re-enters the stream.
            while True:
                saw_message_in_this_receive_call = False
                response: types.LiveServerMessage
                async for response in self._session.receive():
                    saw_message_in_this_receive_call = True
                    log.debug("Received response from Gemini:", response=str(response)[:])  # log a preview of the raw response for debugging Temp

                    # ── 1. TOOL CALLS are top-level on Live API responses. ──────────────────────────────────────────       
                    if response.tool_call and response.tool_call.function_calls:
                        for function_call in response.tool_call.function_calls:
                            yield {
                                "type": "tool_call",
                                "name": function_call.name,
                                "args": dict(function_call.args or {}),
                                "call_id": getattr(function_call, "id", None),
                            }
                        log.debug("gemini_tool_call_detected", tool_names=[fc.name for fc in response.tool_call.function_calls])

                    server_content = getattr(response, "server_content", None)
                    if not server_content:
                        continue
                    
                    # if getattr(server_content, "interrupted", False):
                    #     log.info("gemini_interrupted")
                    #     yield {"type": "interrupted"}

                    # 2) Model output: audio/text parts.
                    model_turn = server_content.model_turn
                    if model_turn and model_turn.parts:
                        for part in model_turn.parts:
                            ## Handle text
                            if getattr(part, "text", None):
                                log.debug("Received gemini_text_chunk", length=len(part.text or ""))
                                if hasattr(part, "thought") and not part.thought:
                                    yield {"type": "text", "text": part.text}

                            ## Handle audio
                            inline_data = getattr(part, "inline_data", None)
                            if inline_data and inline_data.data:
                                audio_data = inline_data.data
                                log.debug("Received gemini_audio_chunk", bytes=len(audio_data))
                                yield {"type": "audio", "data": audio_data}

                    # 3) Speech transcriptions.
                    ## Transcriptions of User Input
                    input_trans = getattr(server_content, "input_transcription", None)
                    if input_trans and getattr(input_trans, "text", None):
                        log.debug("gemini_input_transcript", text=input_trans.text[:80])
                        yield {"type": "input_transcript", "text": input_trans.text}

                    ## Transcriptions of Model Output
                    output_trans = getattr(server_content, "output_transcription", None)
                    if output_trans and getattr(output_trans, "text", None):
                        log.debug("gemini_output_transcript", text=output_trans.text[:100])
                        yield {"type": "output_transcript", "text": output_trans.text}


                    # 4) Turn complete signal.
                    if server_content.turn_complete:
                        log.debug("gemini_turn_complete")
                        yield {"type": "turn_complete"} 
                
                # ── 5. DEAD CONNECTION DETECTOR ────────────────────────────────
                if not saw_message_in_this_receive_call:
                    log.debug("gemini_receive_no_message", message="No messages received in this call to session.receive(). This may indicate a silent disconnection or a network issue.")
                    yield {"type": "session_closed","reason": "receive() finished AS silent_disconnect"}
                    return # Kills the while True loop safely!
                # Tiny cooperative pause before the next turn-scoped receive().
                await asyncio.sleep(0.01)


        except Exception as exc:
            error_msg = str(exc)
            # 1. Catch known Gemini Live API bugs (e.g., fast barge-in panic)
            if "1008" in error_msg and  "Operation is not implemented" in error_msg:
                log.error("gemini_1008_live_api_bug", error=error_msg)
                yield {
                "type": "session_closed",
                "reason": "gemini_live_1008",
                "retryable": True,
                }
                return
            # 2. Catch normal WebSocket closures (Not actual errors!)
            # Common "normal close" cases from the upstream websocket.
            if "1000" in error_msg or "1001" in error_msg:
                log.info("gemini_session_closed_by_server", reason=error_msg)
                yield {"type": "session_closed", "reason": error_msg}
                return

            log.error("gemini_receive_error", error=error_msg)
            yield {"type": "error", "message": error_msg}
            return


    # =========================================================================
    # LIFECYCLE MANAGEMENT
    # =========================================================================
    async def __aenter__(self) -> "GeminiLiveHandler":
        """Opens the WebSocket to Gemini's servers."""
        log.info("gemini_session_connecting", model=settings.gemini_model )

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
        Close the Gemini Live session safely.
        Called automatically when exiting the `async with` block.
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
