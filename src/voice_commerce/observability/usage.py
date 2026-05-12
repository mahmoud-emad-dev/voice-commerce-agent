from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any

from voice_commerce.config.settings import settings
from voice_commerce.observability import costs, metrics

_usage_lock = Lock()
_usage_by_tenant: dict[str, dict[str, Any]] = {}


def _empty_usage_bucket() -> dict[str, Any]:
    return {
        "text_input_tokens": 0,
        "text_output_tokens": 0,
        "audio_input_tokens": 0,
        "audio_output_tokens": 0,
        "audio_input_seconds": 0.0,
        "audio_output_seconds": 0.0,
        "tool_calls": 0,
        "estimated_cost_usd": 0.0,
        "cost_breakdown": defaultdict(float),
        "tool_calls_by_name": defaultdict(int),
        "sources": defaultdict(int),
    }


def _get_bucket(tenant_id: str | None, model: str | None = None) -> tuple[str, str, dict[str, Any]]:
    resolved_tenant_id = tenant_id or settings.demo_tenant_id
    resolved_model = model or settings.gemini_model
    tenant_bucket = _usage_by_tenant.setdefault(resolved_tenant_id, {})
    usage_bucket = tenant_bucket.setdefault(resolved_model, _empty_usage_bucket())
    return resolved_tenant_id, resolved_model, usage_bucket


def reset_usage_state() -> None:
    with _usage_lock:
        _usage_by_tenant.clear()


def usage_snapshot() -> dict[str, Any]:
    with _usage_lock:
        tenants: dict[str, Any] = {}
        for tenant_id, models in _usage_by_tenant.items():
            tenants[tenant_id] = {}
            for model, bucket in models.items():
                tenants[tenant_id][model] = {
                    "text_input_tokens": bucket["text_input_tokens"],
                    "text_output_tokens": bucket["text_output_tokens"],
                    "audio_input_tokens": bucket["audio_input_tokens"],
                    "audio_output_tokens": bucket["audio_output_tokens"],
                    "audio_input_seconds": round(bucket["audio_input_seconds"], 4),
                    "audio_output_seconds": round(bucket["audio_output_seconds"], 4),
                    "tool_calls": bucket["tool_calls"],
                    "estimated_cost_usd": round(bucket["estimated_cost_usd"], 8),
                    "cost_breakdown": {
                        key: round(value, 8) for key, value in bucket["cost_breakdown"].items()
                    },
                    "tool_calls_by_name": dict(bucket["tool_calls_by_name"]),
                    "sources": dict(bucket["sources"]),
                }
        return {"tenants": tenants}


def _record_cost(bucket: dict[str, Any], kind: str, amount_usd: float) -> None:
    if amount_usd <= 0:
        return
    bucket["estimated_cost_usd"] += amount_usd
    bucket["cost_breakdown"][kind] += amount_usd


def record_text_input(
    tenant_id: str | None,
    text: str,
    *,
    source: str,
    model: str | None = None,
) -> None:
    if not settings.cost_tracking_enabled:
        return
    tokens = costs.estimate_text_tokens(text)
    cost_usd = costs.text_input_cost(tokens)
    with _usage_lock:
        resolved_tenant_id, resolved_model, bucket = _get_bucket(tenant_id, model)
        bucket["text_input_tokens"] += tokens
        bucket["sources"][source] += tokens
        _record_cost(bucket, "text_input", cost_usd)
    metrics.observe_text_usage(
        resolved_tenant_id,
        resolved_model,
        tokens,
        source=source,
        direction="input",
    )
    metrics.observe_estimated_cost(resolved_tenant_id, resolved_model, cost_usd, kind="text_input")


def record_text_output(
    tenant_id: str | None,
    text: str,
    *,
    source: str,
    model: str | None = None,
) -> None:
    if not settings.cost_tracking_enabled:
        return
    tokens = costs.estimate_text_tokens(text)
    cost_usd = costs.text_output_cost(tokens)
    with _usage_lock:
        resolved_tenant_id, resolved_model, bucket = _get_bucket(tenant_id, model)
        bucket["text_output_tokens"] += tokens
        bucket["sources"][source] += tokens
        _record_cost(bucket, "text_output", cost_usd)
    metrics.observe_text_usage(
        resolved_tenant_id,
        resolved_model,
        tokens,
        source=source,
        direction="output",
    )
    metrics.observe_estimated_cost(resolved_tenant_id, resolved_model, cost_usd, kind="text_output")


def record_audio_input(
    tenant_id: str | None,
    seconds: float,
    *,
    source: str,
    model: str | None = None,
) -> None:
    if not settings.cost_tracking_enabled:
        return
    clean_seconds = max(seconds, 0.0)
    tokens = costs.estimate_audio_tokens(clean_seconds)
    cost_usd = costs.audio_input_cost(tokens)
    with _usage_lock:
        resolved_tenant_id, resolved_model, bucket = _get_bucket(tenant_id, model)
        bucket["audio_input_tokens"] += tokens
        bucket["audio_input_seconds"] += clean_seconds
        bucket["sources"][source] += tokens
        _record_cost(bucket, "audio_input", cost_usd)
    metrics.observe_audio_usage(
        resolved_tenant_id,
        resolved_model,
        seconds=clean_seconds,
        tokens=tokens,
        source=source,
        direction="input",
    )
    metrics.observe_estimated_cost(resolved_tenant_id, resolved_model, cost_usd, kind="audio_input")


def record_audio_output(
    tenant_id: str | None,
    seconds: float,
    *,
    source: str,
    model: str | None = None,
) -> None:
    if not settings.cost_tracking_enabled:
        return
    clean_seconds = max(seconds, 0.0)
    tokens = costs.estimate_audio_tokens(clean_seconds)
    cost_usd = costs.audio_output_cost(tokens)
    with _usage_lock:
        resolved_tenant_id, resolved_model, bucket = _get_bucket(tenant_id, model)
        bucket["audio_output_tokens"] += tokens
        bucket["audio_output_seconds"] += clean_seconds
        bucket["sources"][source] += tokens
        _record_cost(bucket, "audio_output", cost_usd)
    metrics.observe_audio_usage(
        resolved_tenant_id,
        resolved_model,
        seconds=clean_seconds,
        tokens=tokens,
        source=source,
        direction="output",
    )
    metrics.observe_estimated_cost(
        resolved_tenant_id,
        resolved_model,
        cost_usd,
        kind="audio_output",
    )


def record_tool_call(tenant_id: str | None, tool_name: str, *, model: str | None = None) -> None:
    if not settings.cost_tracking_enabled:
        return
    cost_usd = costs.tool_call_cost(1)
    with _usage_lock:
        resolved_tenant_id, resolved_model, bucket = _get_bucket(tenant_id, model)
        bucket["tool_calls"] += 1
        bucket["tool_calls_by_name"][tool_name] += 1
        _record_cost(bucket, "tool_call", cost_usd)
    metrics.observe_tool_usage(resolved_tenant_id, resolved_model, tool_name)
    metrics.observe_estimated_cost(resolved_tenant_id, resolved_model, cost_usd, kind="tool_call")
