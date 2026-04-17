from __future__ import annotations

import audioop


# =============================================================================
# AUDIO FORMAT CONSTANTS
# =============================================================================


# Gemini Live API output format
GEMINI_OUTPUT_SAMPLE_RATE: int = 24_000   # Hz — Gemini outputs at 24kHz
GEMINI_OUTPUT_BIT_DEPTH: int = 16          # bits per sample (s16le)
GEMINI_OUTPUT_CHANNELS: int = 1            # mono audio
GEMINI_OUTPUT_BYTES_PER_SAMPLE: int = GEMINI_OUTPUT_BIT_DEPTH // 8  # = 2
 
# Gemini Live API input format (used in Phase 5 for microphone capture)
MIC_SAMPLE_RATE: int = 16_000    # Hz — Gemini expects 16kHz mono PCM input
GEMINI_INPUT_BIT_DEPTH: int = 16
GEMINI_INPUT_CHANNELS: int = 1
MIC_BYTES_PER_SAMPLE: int = GEMINI_INPUT_BIT_DEPTH // 8  # = 2
# The widget worklet currently emits one render quantum at a time:
# 128 samples * 2 bytes = 256 bytes. Anything above this drops all mic audio.
MIN_MIC_CHUNK_BYTES: int = 256
MIC_SILENCE_RMS_THRESHOLD: int = 30
 
# Derived constants — computed once, used everywhere
# How many bytes arrive per second from Gemini's audio output
GEMINI_OUTPUT_BYTES_PER_SECOND: int = (
    GEMINI_OUTPUT_SAMPLE_RATE
    * GEMINI_OUTPUT_BYTES_PER_SAMPLE
    * GEMINI_OUTPUT_CHANNELS
)  # = 24000 * 2 * 1 = 48,000 bytes/second
 
# Minimum meaningful chunk size to forward to browser
# Smaller chunks = more WebSocket messages = more overhead
# Larger chunks = higher latency before first sound
# 4096 bytes = ~85ms of audio at 24kHz — good balance
MIN_CHUNK_BYTES: int = 4096




def is_valid_audio_chunk(data: bytes) -> bool:
    if not data:
        return False
    if len(data) % GEMINI_OUTPUT_BYTES_PER_SAMPLE != 0:
        return False
    return True


def is_meaningful_mic_chunk(data: bytes) -> bool:
    """
    Returns True only for mic chunks that likely contain speech.

    Why:
    - Open-mic mode often streams continuous silence/noise-floor frames.
    - Forwarding all of them can create empty Gemini turns
      (input transcript seen, generation_complete, no response).
    """
    return inspect_mic_chunk(data)["meaningful"]


def get_mic_chunk_rms(data: bytes) -> int:
    """Compute RMS amplitude for a valid PCM s16le mono mic chunk."""
    return audioop.rms(data, MIC_BYTES_PER_SAMPLE)


def inspect_mic_chunk(data: bytes) -> dict[str, int | str | bool]:
    """
    Inspect one PCM mic chunk and return a structured classification.

    This feeds tracing and lets the websocket handler log why a chunk
    was dropped instead of treating every rejection as generic silence.
    """
    if not data:
        return {
            "meaningful": False,
            "reason": "empty",
            "bytes": 0,
            "rms": 0,
        }
    if len(data) < MIN_MIC_CHUNK_BYTES:
        return {
            "meaningful": False,
            "reason": "below_min_chunk_bytes",
            "bytes": len(data),
            "rms": 0,
        }
    if len(data) % MIC_BYTES_PER_SAMPLE != 0:
        return {
            "meaningful": False,
            "reason": "bad_alignment",
            "bytes": len(data),
            "rms": 0,
        }

    rms = get_mic_chunk_rms(data)
    if rms < MIC_SILENCE_RMS_THRESHOLD:
        return {
            "meaningful": False,
            "reason": "below_rms_threshold",
            "bytes": len(data),
            "rms": rms,
        }

    return {
        "meaningful": True,
        "reason": "ok",
        "bytes": len(data),
        "rms": rms,
    }


def chunk_duration_ms(chunk: bytes) -> float:

    if not chunk:
        return 0.0
    num_samples = len(chunk) / GEMINI_OUTPUT_BYTES_PER_SAMPLE
    duration_seconds = num_samples / GEMINI_OUTPUT_SAMPLE_RATE
    return duration_seconds * 1000


def get_browser_audio_config() -> dict:
    return {
            "sample_rate": GEMINI_OUTPUT_SAMPLE_RATE,   # 24000
            "bit_depth": GEMINI_OUTPUT_BIT_DEPTH,       # 16
            "channels": GEMINI_OUTPUT_CHANNELS,          # 1
            "encoding": "pcm_s16le",
            # The browser must create AudioContext({sampleRate: 24000})
            # to match this. Wrong sample rate = chipmunk or slowed-down audio.
        }

def get_mic_audio_config() -> dict:
    return {
        "sample_rate": MIC_SAMPLE_RATE,  # 16000
        "bit_depth": GEMINI_INPUT_BIT_DEPTH,  # 16
        "channels": GEMINI_INPUT_CHANNELS,  # 1
        "encoding": "pcm_s16le",
            # WHY SEND THIS:
            #   Hardcoding 16000 in JavaScript is fragile — it must match
            #   GEMINI_INPUT_SAMPLE_RATE exactly. Sending it from Python means
            #   one source of truth. If Google changes the required input rate,
            #   we change audio_processor.py and the browser auto-adapts.
    }
