# Observability

## Goal

Phase 13 adds production-facing observability for the voice commerce app without exposing
sensitive prompts, transcripts, tenant keys, or raw cart payloads by default.

The observability layer currently includes:

- structured logging with `tenant_id` and `session_id` context
- Prometheus metrics at `/metrics`
- startup, warmup, tool, RAG, Gemini, and turn latency metrics
- estimated Gemini usage and cost tracking
- optional Langfuse tracing behind feature flags

## Environment

Relevant variables from `.env`:

```env
APP_ENV=local
LOG_LEVEL=INFO
LOG_JSON=
LOG_FILE_PATH=
DEBUG_PAYLOAD_LOGS=false

METRICS_ENABLED=true
METRICS_REQUIRE_ADMIN_KEY=false

LLM_TRACING_ENABLED=false
LANGFUSE_ENABLED=false
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
TRACE_PAYLOAD_PREVIEWS=false
TRACE_PREVIEW_MAX_CHARS=200

COST_TRACKING_ENABLED=true
GEMINI_ESTIMATED_TEXT_CHARS_PER_TOKEN=4
GEMINI_ESTIMATED_AUDIO_TOKENS_PER_SECOND=32
GEMINI_TEXT_INPUT_COST_PER_1M_TOKENS=0
GEMINI_TEXT_OUTPUT_COST_PER_1M_TOKENS=0
GEMINI_AUDIO_INPUT_COST_PER_1M_TOKENS=0
GEMINI_AUDIO_OUTPUT_COST_PER_1M_TOKENS=0
GEMINI_CACHE_READ_COST_PER_1M_TOKENS=0
GEMINI_CACHE_WRITE_COST_PER_1M_TOKENS=0
GEMINI_TOOL_CALL_COST_PER_1K=0
```

## Logging

Logging is configured in `src/voice_commerce/observability/logging.py`.

Behavior:

- local/debug defaults to console logs
- non-debug defaults to JSON logs
- optional file logging is enabled with `LOG_FILE_PATH`
- `tenant_id`, `session_id`, and optional request context are bound through `structlog.contextvars`

Sensitive values are redacted before structured payload logging when possible. Common redacted
keys include:

- `tenant_key`
- `api_key`
- `authorization`
- `gemini_api_key`
- `wc_consumer_key`
- `wc_consumer_secret`

`DEBUG_PAYLOAD_LOGS=true` should only be used for deliberate local debugging.

## Metrics

Metrics are exposed at:

- `GET /metrics`

Access rules:

- when `APP_DEBUG=true`, metrics are open locally
- when `APP_DEBUG=false` and `METRICS_REQUIRE_ADMIN_KEY=true`, send `X-Admin-Key`
- when `METRICS_ENABLED=false`, the route returns `404`

Example local request:

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/metrics"
```

Example production-style request:

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/metrics" -Headers @{ "X-Admin-Key" = "dev-admin-key" }
```

### Current metric groups

Base:

- `voice_app_info`
- `voice_ready_state`
- `voice_active_sessions`

Startup and warmup:

- `voice_startup_duration_seconds`
- `voice_startup_step_duration_seconds`
- `voice_startup_steps_total`

Tools:

- `voice_tool_calls_total`
- `voice_tool_call_duration_seconds`

RAG and vector search:

- `voice_rag_searches_total`
- `voice_rag_search_duration_seconds`
- `voice_rag_search_results_count`
- `voice_embedding_duration_seconds`
- `voice_qdrant_query_duration_seconds`
- `voice_qdrant_upsert_duration_seconds`
- `voice_qdrant_points_upserted_total`

Gemini and turns:

- `voice_gemini_session_open_duration_seconds`
- `voice_gemini_sessions_total`
- `voice_gemini_session_errors_total`
- `voice_gemini_reconnects_total`
- `voice_turns_total`
- `voice_turn_duration_seconds`
- `voice_time_to_first_audio_seconds`
- `voice_time_to_first_transcript_seconds`
- `voice_audio_input_bytes_total`
- `voice_audio_output_bytes_total`
- `voice_audio_input_seconds_total`
- `voice_audio_output_seconds_total`
- `voice_audio_chunks_in_total`
- `voice_audio_chunks_out_total`

Usage and cost:

- `voice_usage_text_input_tokens_total`
- `voice_usage_text_output_tokens_total`
- `voice_usage_audio_input_seconds_total`
- `voice_usage_audio_output_seconds_total`
- `voice_usage_audio_input_tokens_total`
- `voice_usage_audio_output_tokens_total`
- `voice_usage_tool_calls_total`
- `voice_estimated_cost_usd_total`

## Metric label rules

Safe labels currently used:

- `tenant_id`
- `tool_name`
- `status`
- `reason`
- `model`
- `source`
- `kind`

Labels intentionally avoided:

- `session_id`
- raw prompt text
- transcript text
- product names
- cart item names
- tenant keys

This avoids high-cardinality metrics and prevents sensitive data leakage.

## Usage and cost tracking

Usage and cost tracking is process-local today.

Current admin endpoint:

- `GET /admin/usage`

Requires:

- `X-Admin-Key`

Example:

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/admin/usage" -Headers @{ "X-Admin-Key" = "dev-admin-key" }
```

Important limitations:

- text tokens are estimated using `GEMINI_ESTIMATED_TEXT_CHARS_PER_TOKEN`
- audio tokens are estimated using `GEMINI_ESTIMATED_AUDIO_TOKENS_PER_SECOND`
- costs are only as accurate as the configured pricing values
- totals reset on process restart because this is not persisted yet

That is acceptable for Phase 13 because the goal is operational visibility, not billing.

## Langfuse tracing

Langfuse tracing is real but optional.

Enable it with:

```env
LLM_TRACING_ENABLED=true
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://cloud.langfuse.com
```

Default tracing behavior:

- no network calls when tracing is disabled
- payload previews are disabled by default
- tracing metadata is redacted through the same redaction helpers used for structured logs

If you explicitly want previews in Langfuse:

```env
TRACE_PAYLOAD_PREVIEWS=true
TRACE_PREVIEW_MAX_CHARS=200
```

Even with previews enabled, keep them short and use them only for controlled debugging.

### Current trace boundaries

- session start and finish
- Gemini session connect/connect-failed events
- Gemini text sends
- context injections
- tool results sent back to Gemini
- tool observations
- RAG search observations

## Manual smoke test

Run the app:

```bash
uv run uvicorn voice_commerce.main:app --reload --port 8000
```

Check core endpoints:

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/health"
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/ready"
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/rag/stats"
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/metrics"
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/admin/usage" -Headers @{ "X-Admin-Key" = "dev-admin-key" }
```

Then exercise:

1. connect to `/ws/voice`
2. send a text query
3. send an audio query
4. trigger product search
5. trigger add-to-cart or checkout tool
6. check `/metrics` again
7. check `/admin/usage` again

Expected:

- active session gauge rises during live use
- tool and RAG counters increase
- usage and cost counters increase
- readiness stays meaningful

## Next likely follow-ups

Natural post-Phase-13 improvements:

1. persist usage totals instead of keeping them only in memory
2. add Grafana dashboards on top of `/metrics`
3. add alerting for repeated Gemini failures or slow TTFA
4. connect estimated cost totals to tenant billing later if needed
