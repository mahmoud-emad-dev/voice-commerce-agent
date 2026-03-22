from __future__ import annotations
from  collections.abc import AsyncGenerator
from typing import Any


import structlog
from google import genai
from google.genai import types


from voice_commerce.config.settings import settings


log = structlog.get_logger(__name__)


class GeminiLiveHandler:

    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key) 
        self._session: Any = None
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
            output_audio_transcription=types.AudioTranscriptionConfig()

            )
            

    
    def _build_system_prompt(self) -> str:
        """The 'Rules' the AI must follow."""
        return "You are a friendly Voice Shopping Assistant. Keep answers short."   
    

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

    
    async def receive_events(self) -> AsyncGenerator[dict[str, Any], None]:
        if self._session is None:
            raise RuntimeError("Cannot receive: Gemini session is not connected.")
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
                    # return
        except Exception as e:
            log.error("gemini_receive_error", error=str(e))
            yield {"type": "error", "message": "Brain connection lost."}


    async def __aenter__(self) -> "GeminiLiveHandler":
        log.info(
            "gemini_session_connecting",
            model=settings.gemini_model,
        )

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
