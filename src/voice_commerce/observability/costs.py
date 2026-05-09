from __future__ import annotations

import math

from voice_commerce.config.settings import settings


def estimate_text_tokens(text: str) -> int:
    """Estimate token count from text length using a configurable chars/token ratio."""
    ratio = max(settings.gemini_estimated_text_chars_per_token, 1.0)
    return max(0, math.ceil(len(str(text or "")) / ratio))


def estimate_audio_tokens(seconds: float) -> int:
    """Estimate audio tokens from audio duration using a configurable token rate."""
    rate = max(settings.gemini_estimated_audio_tokens_per_second, 1.0)
    return max(0, math.ceil(max(float(seconds or 0.0), 0.0) * rate))


def _per_token_cost(cost_per_million_tokens: float) -> float:
    return max(float(cost_per_million_tokens or 0.0), 0.0) / 1_000_000


def text_input_cost(tokens: int) -> float:
    return tokens * _per_token_cost(settings.gemini_text_input_cost_per_1m_tokens)


def text_output_cost(tokens: int) -> float:
    return tokens * _per_token_cost(settings.gemini_text_output_cost_per_1m_tokens)


def audio_input_cost(tokens: int) -> float:
    return tokens * _per_token_cost(settings.gemini_audio_input_cost_per_1m_tokens)


def audio_output_cost(tokens: int) -> float:
    return tokens * _per_token_cost(settings.gemini_audio_output_cost_per_1m_tokens)


def tool_call_cost(call_count: int) -> float:
    return max(int(call_count or 0), 0) * (max(settings.gemini_tool_call_cost_per_1k, 0.0) / 1000)
