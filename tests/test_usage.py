from __future__ import annotations

from voice_commerce.observability import costs, usage


def test_text_token_estimate_uses_chars_per_token_ratio() -> None:
    assert costs.estimate_text_tokens("abcdefgh") == 2


def test_usage_snapshot_collects_text_audio_and_tool_costs() -> None:
    usage.reset_usage_state()

    usage.record_text_input("demo", "hello world", source="text_message")
    usage.record_text_output("demo", "response", source="text_stream")
    usage.record_audio_input("demo", 1.5, source="audio_stream")
    usage.record_audio_output("demo", 2.0, source="audio_stream")
    usage.record_tool_call("demo", "search_products")

    snapshot = usage.usage_snapshot()
    demo_bucket = snapshot["tenants"]["demo"]["gemini-2.5-flash-native-audio-preview-12-2025"]

    assert demo_bucket["text_input_tokens"] > 0
    assert demo_bucket["text_output_tokens"] > 0
    assert demo_bucket["audio_input_tokens"] > 0
    assert demo_bucket["audio_output_tokens"] > 0
    assert demo_bucket["audio_input_seconds"] == 1.5
    assert demo_bucket["audio_output_seconds"] == 2.0
    assert demo_bucket["tool_calls"] == 1
    assert demo_bucket["tool_calls_by_name"]["search_products"] == 1
