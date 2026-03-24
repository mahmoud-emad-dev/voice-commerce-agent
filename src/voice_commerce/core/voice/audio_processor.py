from __future__ import annotations



# =============================================================================
# AUDIO FORMAT CONSTANTS
# =============================================================================


# Gemini Live API output format
GEMINI_OUTPUT_SAMPLE_RATE: int = 24_000   # Hz — Gemini outputs at 24kHz
GEMINI_OUTPUT_BIT_DEPTH: int = 16          # bits per sample (s16le)
GEMINI_OUTPUT_CHANNELS: int = 1            # mono audio
GEMINI_OUTPUT_BYTES_PER_SAMPLE: int = GEMINI_OUTPUT_BIT_DEPTH // 8  # = 2
 
# Gemini Live API input format (used in Phase 5 for microphone capture)
MIC_SAMPLE_RATE: int = 16_000    # Hz — Gemini expects 16kHz input MIC_SAMPLE_RATE: int = 16_000  GEMINI_INPUT_SAMPLE_RATE
GEMINI_INPUT_BIT_DEPTH: int = 16
GEMINI_INPUT_CHANNELS: int = 1
 
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