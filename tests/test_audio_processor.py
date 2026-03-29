# =============================================================================
# tests/test_audio_processor.py
# =============================================================================
#
# Tests for audio format constants and chunk validation.
# These are pure unit tests — no server, no WebSocket, no Gemini needed.
# =============================================================================

from __future__ import annotations

import struct

from voice_commerce.core.voice.audio_processor import (
    MIC_SAMPLE_RATE,
    GEMINI_OUTPUT_BYTES_PER_SAMPLE,
    GEMINI_OUTPUT_BYTES_PER_SECOND,
    GEMINI_OUTPUT_SAMPLE_RATE,
    chunk_duration_ms,
    get_browser_audio_config,
    is_valid_audio_chunk,
)


class TestAudioConstants:

    def test_output_sample_rate_is_24khz(self) -> None:
        """Gemini outputs at 24kHz — wrong rate = pitch-shifted audio."""
        assert GEMINI_OUTPUT_SAMPLE_RATE == 24_000

    def test_input_sample_rate_is_16khz(self) -> None:
        """Gemini requires 16kHz mic input — must match the MIME type."""
        assert MIC_SAMPLE_RATE == 16_000

    def test_bytes_per_sample_is_2(self) -> None:
        """s16le = 2 bytes per sample (16 bits / 8 = 2)."""
        assert GEMINI_OUTPUT_BYTES_PER_SAMPLE == 2

    def test_bytes_per_second_is_correct(self) -> None:
        """24000 samples/s × 2 bytes/sample × 1 channel = 48000 bytes/s."""
        assert GEMINI_OUTPUT_BYTES_PER_SECOND == 48_000


class TestChunkValidation:

    def _make_pcm(self, num_samples: int) -> bytes:
        """Create a valid PCM s16le chunk with num_samples samples."""
        return struct.pack(f"<{num_samples}h", *([0] * num_samples))

    def test_empty_chunk_is_invalid(self) -> None:
        assert is_valid_audio_chunk(b"") is False

    def test_odd_byte_chunk_is_invalid(self) -> None:
        """s16le requires even byte count — 1 byte = incomplete sample."""
        assert is_valid_audio_chunk(b"\x00") is False
        assert is_valid_audio_chunk(b"\x00\x01\x02") is False

    def test_even_byte_chunk_is_valid(self) -> None:
        chunk = self._make_pcm(100)  # 200 bytes — valid
        assert is_valid_audio_chunk(chunk) is True

    def test_minimum_real_chunk_is_valid(self) -> None:
        """4096-byte chunk (2048 samples) is the standard browser chunk size."""
        chunk = self._make_pcm(2048)  # = 4096 bytes
        assert is_valid_audio_chunk(chunk) is True


class TestChunkDuration:

    def test_zero_duration_for_empty(self) -> None:
        assert chunk_duration_ms(b"") == 0.0

    def test_duration_calculation(self) -> None:
        # 4800 bytes = 2400 samples at 16-bit = 2400/24000 s = 100ms
        samples = 2400
        chunk = bytes(samples * 2)
        ms = chunk_duration_ms(chunk)
        assert abs(ms - 100.0) < 0.1, f"Expected ~100ms, got {ms}ms"

    def test_one_second_of_audio(self) -> None:
        # 48000 bytes = 24000 samples = exactly 1 second at 24kHz
        one_second = bytes(GEMINI_OUTPUT_BYTES_PER_SECOND)
        ms = chunk_duration_ms(one_second)
        assert abs(ms - 1000.0) < 1.0, f"Expected ~1000ms, got {ms}ms"


class TestBrowserAudioConfig:

    def test_returns_dict(self) -> None:
        cfg = get_browser_audio_config()
        assert isinstance(cfg, dict)

    def test_has_required_fields(self) -> None:
        cfg = get_browser_audio_config()
        assert "sample_rate" in cfg
        assert "bit_depth" in cfg
        assert "channels" in cfg
        assert "encoding" in cfg

    def test_sample_rate_matches_constant(self) -> None:
        cfg = get_browser_audio_config()
        assert cfg["sample_rate"] == GEMINI_OUTPUT_SAMPLE_RATE  # 24000

    def test_encoding_is_pcm_s16le(self) -> None:
        cfg = get_browser_audio_config()
        assert "pcm" in cfg["encoding"].lower()
        assert "16" in cfg["encoding"]