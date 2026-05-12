# Voice Commerce Agent

Real-time AI voice commerce for storefronts. Customers can speak naturally, search products semantically, see the page respond with highlights and filters, add items to cart, and complete a guided checkout flow through one embeddable widget.

Built with FastAPI, Gemini Live API, Qdrant, sentence-transformers, PostgreSQL-ready session persistence, Prometheus metrics, Langfuse tracing, and Docker-based deployment assets.

<p align="center">
  <img src="docs/demo/Demo%20Gif%201.gif" alt="Voice Commerce Agent live demo" width="100%" />
</p>

<p align="center"><em>Live demo: natural voice query -> semantic product search -> browser highlights -> cart and checkout actions.</em></p>

---

## What This Project Demonstrates

This is not a basic chatbot. It is an end-to-end voice commerce system with real-time audio, tool calling, semantic retrieval, browser-side actions, tenant-aware catalog isolation, observability, and deployment hardening.

Strong engineering points:

- Real-time bidirectional voice over WebSocket using Gemini Live.
- Semantic product search with local embeddings and Qdrant vector retrieval.
- Browser action layer that turns AI tool results into visible storefront changes.
- Clean separation between routes, handlers, services, tools, RAG, and browser actions.
- Typed Pydantic contracts at external boundaries instead of loose dictionaries.
- CSV-backed demo catalog for reliable local demos, with WooCommerce integration kept isolated.
- Tenant-aware product catalog, session, and usage paths.
- Prometheus metrics, structured logging, usage/cost tracking, and optional Langfuse traces.
- Docker Compose stack with app, Qdrant, PostgreSQL, nginx, systemd, and CI/CD deployment assets.

---

## Current Status

Implemented:

- Voice and text conversation through Gemini Live.
- Audio input and output streaming.
- Tool calling for products, cart, and checkout.
- RAG product search with sentence-transformers and Qdrant.
- Browser DOM actions through `static/widget.js`.
- Embeddable single-file storefront widget.
- Demo storefront and repeatable CSV catalog.
- Qdrant-safe tenant product point IDs.
- Tenant-aware catalog sync and search.
- Admin tenant APIs and tenant settings.
- PostgreSQL-backed session/tenant persistence path.
- Structured logging with tenant/session context.
- Prometheus `/metrics` endpoint.
- `/admin/usage` usage and estimated cost endpoint.
- Langfuse tracing integration behind feature flags.
- Docker, Compose, production env template, nginx config, systemd unit, and GitHub Actions deploy workflow.

Validated locally:

- `91 passed, 2 deselected` for non-integration tests.
- Ruff passes.
- `/health` and `/ready` pass.
- `/metrics` records startup, RAG, Qdrant, Gemini, turn, audio, tool, and usage metrics.
- `/admin/usage` records text, audio, and tool usage.
- Checkout tool metrics validated for `search_products`, `add_to_cart`, `begin_checkout`, `set_checkout_option`, and `confirm_checkout`.

Deployment note:

- Phase 14 deployment assets are present and partially validated.
- Docker image build starts correctly, but the current ML dependency stack pulls a large PyTorch/CUDA wheel set. Image slimming is the main remaining deployment optimization before a lightweight VPS deploy.

---

## Demo Screenshots

<p align="center">
  <img src="docs/demo/Screenshot%201.png" alt="Voice widget open on storefront" width="100%" />
</p>

<p align="center"><em>Storefront with the voice widget open.</em></p>

<table>
  <tr>
    <td width="50%">
      <img src="docs/demo/Screenshot%202%20__%20Search%20results%20in%20action.png" alt="Semantic search results and highlights" width="100%" />
      <p><strong>Search results in action</strong><br />Semantic retrieval returns relevant products and the browser highlights them while the assistant explains the results.</p>
    </td>
    <td width="50%">
      <img src="docs/demo/Screenshot%203%20__Cart%20%2B%20checkout%20flow.png" alt="Cart and guided checkout" width="100%" />
      <p><strong>Cart and checkout flow</strong><br />Voice-guided checkout with shipping, payment selection, order summary, and confirmation.</p>
    </td>
  </tr>
  <tr>
    <td colspan="2">
      <img src="docs/demo/Screenshot%204%20__%20Voice-guided%20filtering%20and%20ranking.png" alt="Voice-guided filtering and ranking" width="100%" />
      <p><strong>Voice-guided filtering and ranking</strong><br />The assistant applies filters and ranking actions directly to the storefront DOM.</p>
    </td>
  </tr>
</table>

---

## Architecture

```text
Browser storefront
  -> static/widget.js
  -> WebSocket /ws/voice
  -> VoiceWebSocketHandler
  -> GeminiLiveHandler
  -> ToolDispatcher
  -> product/cart/checkout tools
  -> RAG service
  -> embedder + Qdrant vector store
  -> CSV demo catalog or WooCommerce client
  -> ActionDispatcher
  -> browser DOM actions, audio, transcripts, cart, checkout UI
```

### Runtime Flow

1. The widget captures typed text or microphone audio.
2. The FastAPI WebSocket route accepts `/ws/voice` and delegates to `VoiceWebSocketHandler`.
3. The handler runs two tasks: browser-to-Gemini and Gemini-to-browser.
4. Gemini responds directly with audio/text or emits tool calls.
5. `ToolDispatcher` executes product, cart, checkout, or RAG-backed tools.
6. Tool results return to Gemini as structured context.
7. `ActionDispatcher` maps results to browser actions.
8. The widget executes highlights, filters, cart updates, checkout rendering, and audio playback.

### Why The Architecture Matters

- Routes stay thin and only wire HTTP/WebSocket entrypoints.
- Session orchestration lives in `handlers/`.
- External integrations are isolated in one boundary file each.
- Tools return typed `ToolResponse` objects.
- Browser actions have typed Pydantic models and a separate dispatcher.
- RAG, catalog loading, and vector storage are isolated from Gemini logic.
- Observability is centralized in `src/voice_commerce/observability/`.

---

## Key Technical Decisions

### Gemini Live Instead Of REST Completion

The app uses Gemini Live for persistent bidirectional audio. This avoids the slow STT -> LLM -> TTS chain and enables natural turn-taking, interruption handling, transcripts, audio output, and tool calling in the same session.

### RAG Before Storefront Actions

Product discovery is not keyword search. The assistant embeds catalog products, searches Qdrant, reranks results, then sends both natural language context to Gemini and structured browser actions to the widget.

### Two Dispatchers Instead Of One God Function

`ToolDispatcher` handles AI tool execution. `ActionDispatcher` handles UI effects. This keeps product/cart/checkout logic independent from browser DOM concerns.

### CSV Demo Path Plus WooCommerce Boundary

The demo uses `tests/products.csv` as runtime data so the full system can be tested without a live store. WooCommerce remains isolated in `services/woocommerce_client.py` for real-store integration.

### Tenant-Aware Catalogs And Usage

Tenant IDs flow through catalog sync, RAG search, tool execution, logs, metrics, and usage. Qdrant points are generated safely for tenant/product isolation.

### Observability Is Built In

The app emits structured logs, Prometheus metrics, usage summaries, estimated cost counters, and optional Langfuse traces. Metrics avoid high-cardinality labels like `session_id`.

### Deployment As A First-Class Concern

The repo includes Docker, Compose, nginx, systemd, production env templates, and GitHub Actions deploy workflow. The remaining deployment improvement is image-size optimization for the ML dependency stack.

---

## Feature Set

### Voice And Text

- Gemini Live bidirectional audio session.
- Browser microphone capture through AudioWorklet.
- PCM streaming over WebSocket.
- Gapless audio playback scheduling.
- Input and output transcripts.
- Text input path for faster testing and accessibility.
- Session refresh handling for Gemini session lifetime limits.

### Product Search And RAG

- Sentence-transformer embeddings with multilingual support.
- Qdrant vector store in memory or server mode.
- Catalog sync on startup.
- Tenant-scoped vector search.
- Category intelligence injected into the system prompt.
- Heuristic reranking for category-sensitive product queries.
- Pagination and de-duplication across search turns.

### Tools

- Product search.
- Product details.
- Category discovery.
- Add to cart.
- Show/remove cart items.
- Begin checkout.
- Set checkout options.
- Confirm checkout.
- Session-aware tool execution.

### Browser Actions

- Product highlighting.
- Product scrolling.
- Category filter application.
- Sort application.
- Cart badge updates.
- Cart drawer rendering.
- Quick-view modal support.
- Checkout overlay rendering.

### Multi-Tenant Foundation

- Tenant settings and API key path.
- Tenant-scoped catalog path.
- Tenant-scoped RAG sync and search.
- Tenant context in logs and metrics.
- Admin tenant route foundation.
- PostgreSQL-backed tenant/session persistence path.

### Observability

- Structured logging through `structlog`.
- Tenant and session context binding.
- Prometheus `/metrics` route.
- Startup and warmup metrics.
- RAG, embedding, Qdrant, and tool metrics.
- Gemini session and turn latency metrics.
- Audio input/output bytes, chunks, seconds, and estimated tokens.
- `/admin/usage` usage summary.
- Estimated cost tracking with configurable prices.
- Optional Langfuse tracing.

### Deployment

- Multi-stage Dockerfile.
- Non-root container runtime user.
- Container healthcheck.
- Docker Compose stack for app, Qdrant, and PostgreSQL.
- Production Compose override for GHCR images.
- Production env template.
- nginx reverse proxy config with WebSocket upgrade headers.
- systemd unit for the Compose stack.
- GitHub Actions test/build/push/deploy workflow.
- Deployment runbook in `docs/deployment.md`.

---

## Repository Structure

```text
src/voice_commerce/
  api/
    middleware/              CORS middleware
    routes/                  FastAPI route wiring
  config/                    pydantic-settings configuration
  core/
    actions/                 browser action models and dispatcher
    rag/                     embedder, retriever, Qdrant wrapper
    state/                   checkout/session state models
    tools/                   Gemini tool schemas, dispatcher, implementations
    voice/                   Gemini Live handler and audio helpers
  handlers/                  WebSocket session orchestration
  models/                    Pydantic contracts
  observability/             logging, metrics, usage, costs, tracing
  services/                  CSV, WooCommerce, RAG, session, tenant services
  main.py                    app factory, lifespan, route registration

static/
  widget.js                  embeddable storefront widget
  embed_demo.html            local demo storefront
  test_client.html           developer test harness

docs/
  deployment.md              Phase 14 deployment runbook
  observability.md           Phase 13 observability guide
  demo/                      GIF and screenshots

deploy/
  nginx.conf                 production reverse proxy template
  voice-commerce.service     systemd unit for Docker Compose stack

.github/workflows/
  deploy.yml                 test, build, push, deploy workflow
```

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Backend | FastAPI | Async HTTP/WebSocket server |
| Realtime AI | Gemini Live API | Bidirectional audio, transcripts, tool calling |
| Embeddings | sentence-transformers | Local product embeddings |
| Vector DB | Qdrant | Semantic product retrieval |
| Persistence | PostgreSQL + asyncpg | Session and tenant persistence path |
| Models | Pydantic v2 | Typed contracts and validation |
| Config | pydantic-settings | Environment-driven settings |
| Logging | structlog | Structured logs with context |
| Metrics | prometheus-client | Prometheus endpoint and counters/histograms |
| Tracing | Langfuse | Optional LLM traces |
| Packaging | uv | Fast dependency management |
| Runtime | Docker Compose | App, Qdrant, PostgreSQL stack |
| Proxy | nginx | TLS and WebSocket reverse proxy |

---

## Running Locally

### Requirements

- Python 3.12+
- `uv`
- Gemini API key

### Setup

```bash
git clone https://github.com/YOUR_USERNAME/voice-commerce-agent.git
cd voice-commerce-agent
uv sync
cp .env.example .env
```

Set at minimum:

```env
GEMINI_API_KEY=your_key_here
ENABLE_PUBLIC_DEMO=true
```

Start the app:

```bash
uv run uvicorn src.voice_commerce.main:app --reload --port 8000
```

Open:

- Demo storefront: `http://localhost:8000/static/embed_demo.html`
- Health: `http://localhost:8000/health`
- Readiness: `http://localhost:8000/ready`
- Metrics: `http://localhost:8000/metrics`
- Usage: `http://localhost:8000/admin/usage`

### Tests

```bash
uv run ruff check .
uv run pytest tests/ -m "not integration" -q
```

Integration tests that hit Gemini or WooCommerce require real credentials.

---

## Docker And Deployment

Local production-shaped stack:

```bash
cp .env.production.example .env.production
docker compose --env-file .env.production up -d --build
```

Check:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
curl -H "X-Admin-Key: YOUR_ADMIN_KEY" http://127.0.0.1:8000/metrics
```

Production deployment assets:

- `Dockerfile`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `.env.production.example`
- `deploy/nginx.conf`
- `deploy/voice-commerce.service`
- `.github/workflows/deploy.yml`
- `docs/deployment.md`

Read the deployment runbook:

```text
docs/deployment.md
```

---

## Embedding The Widget

Add one script tag to a storefront:

```html
<script
  src="https://voice.example.com/static/widget.js"
  data-ws-url="wss://voice.example.com/ws/voice"
  data-tenant="demo"
  data-theme="auto"
  data-position="bottom-right"
></script>
```

The widget is a dependency-free IIFE. It injects its own CSS, opens the WebSocket, captures mic audio, plays streamed audio, renders transcripts, and executes browser actions.

---

## Observability

Useful endpoints:

- `GET /health`
- `GET /ready`
- `GET /metrics`
- `GET /admin/usage`

Production behavior:

- `APP_DEBUG=false`
- `LOG_JSON=true`
- `METRICS_REQUIRE_ADMIN_KEY=true`
- `ENABLE_PUBLIC_DEMO=false`
- `DEBUG_PAYLOAD_LOGS=false`
- `TRACE_PAYLOAD_PREVIEWS=false`

See:

```text
docs/observability.md
```

---

## Project Phases

Completed or implemented:

- Phase 0: environment setup
- Phase 1: project skeleton
- Phase 2: text pipeline
- Phase 3: Gemini function calling
- Phase 4: text-to-audio output
- Phase 5: microphone audio input
- Phase 6: WooCommerce tool boundary
- Phase 7: RAG integration
- Phase 8: browser actions
- Phase 9: embeddable widget
- Phase 10: demo polish
- Phase 11: Docker, Qdrant, PostgreSQL persistence path
- Phase 12: multi-tenant foundation
- Phase 13: observability
- Phase 14: deployment scaffolding and hardening

Remaining improvement backlog:

- Slim Docker image by forcing CPU-only ML dependencies or externalizing embeddings.
- Run full VPS deployment against a real domain.
- Add production load/rate-limit tests.
- Add persistent billing-grade usage storage.
- Add dashboards and alerts on top of Prometheus metrics.
- Add a production eval suite for synthetic voice-commerce journeys.

---

## Engineering Highlights

This project combines several system concerns that are often built separately:

- realtime audio streaming
- LLM tool calling
- typed backend contracts
- retrieval-augmented product search
- browser automation from AI decisions
- multi-tenant isolation patterns
- production observability
- containerized deployment infrastructure
- CI/CD-ready release path

The main engineering strength is the separation of concerns: Gemini handles conversation, tools handle business operations, RAG handles product retrieval, browser actions handle UI effects, and observability/deployment are treated as first-class system layers.

---

## License

MIT - see [LICENSE](LICENSE).
