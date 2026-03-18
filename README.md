# Voice Commerce Agent

A production-grade, voice-to-voice AI shopping assistant for WooCommerce stores.
Powered by Gemini Live API for native audio processing, with RAG-based product search
and real-time browser control via an embeddable widget.

## What it does

A store visitor says "I need running shoes under $150" and the assistant:
1. Understands the spoken request (Gemini Live, ~400ms latency)
2. Searches the real product catalog semantically (vector RAG, Arabic + English)
3. Responds with natural speech AND highlights matching products on the page
4. Can add items to cart, show the cart, and answer product questions — all by voice

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Language | Python 3.12 | Current LTS, all AI libraries certified |
| Package manager | uv | 10-100x faster than pip, lock file reproducibility |
| Web framework | FastAPI | Async-native, WebSocket built-in, Pydantic integration |
| AI / Voice | Gemini Live API (gemini-2.5-flash-native-audio-preview) | Native audio in/out, 320-800ms latency, no STT+TTS pipeline needed |
| Embeddings | sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2) | Arabic + English confirmed, runs locally |
| Vector DB | Qdrant | In-memory for dev, Docker for production, same client |
| E-commerce | WooCommerce REST API | Standard WooCommerce store integration |
| Config | pydantic-settings | Type-safe config from .env, fails fast on missing vars |
| Logging | structlog | JSON structured logs, queryable in production |

## Setup

### Requirements
- Python 3.12+
- uv (`pip install uv`)
- A Gemini API key (get one at aistudio.google.com)

### Install

```bash
git clone https://github.com/yourname/voice-commerce-agent
cd voice-commerce-agent

# Create virtualenv and install dependencies
uv sync

# Install the project in editable mode (makes imports work)
uv pip install -e .

# Copy and fill in environment variables
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY at minimum
```

### Run

```bash
# Development server (auto-reload)
uv run uvicorn src.voice_commerce.main:app --reload --port 8000

# Check it works
curl http://localhost:8000/health
# → {"status": "ok", "service": "voice-commerce-agent", ...}
```

### Test

```bash
uv run pytest tests/ -v
```

## Build Phases

This project is built incrementally — each phase adds one capability:

| Phase | What it adds | Status |
|---|---|---|
| P0 | Environment setup (Python 3.12, uv, pyproject.toml) | ✅ |
| P1 | Project skeleton (FastAPI, settings, health endpoint, tests) | ✅ |
| P2 | Text ↔ text pipeline (WebSocket + Gemini) | 🔲 |
| P3 | Function calling (tool registry + dispatcher) | 🔲 |
| P4 | Audio output (Gemini → browser audio streaming) | 🔲 |
| P5 | Audio input (mic → PCM → Gemini) | 🔲 |
| P6 | WooCommerce tools (real product data) | 🔲 |
| P7 | RAG integration (semantic search) | 🔲 |
| P8 | Browser actions (AI controls the store page) | 🔲 |
| P9 | Embeddable widget (one script tag) | 🔲 |
| P10 | Demo checkpoint — **CV milestone** | 🔲 |
| P11 | Docker + persistence | 🔲 |
| P12 | Multi-tenancy | 🔲 |
| P13 | Observability | 🔲 |
| P14 | Deployment (VPS + nginx + CI/CD) | 🔲 |

## Project Structure

```
voice-commerce-agent/
├── pyproject.toml          # Project definition, dependencies, tool config
├── .env.example            # Environment variable template
├── src/
│   └── voice_commerce/     # The importable package
│       ├── main.py         # FastAPI app factory + lifespan
│       ├── config/
│       │   └── settings.py # All config (pydantic-settings, reads .env)
│       ├── api/routes/     # HTTP + WebSocket endpoint handlers
│       ├── core/           # Business logic (voice, RAG, tools, actions)
│       ├── handlers/       # WebSocket lifecycle managers
│       ├── services/       # External service clients (WooCommerce, RAG)
│       └── models/         # Pydantic data models (Product, Cart, Session)
├── static/                 # Test client HTML + embeddable widget.js
├── tests/                  # pytest test suite
└── docker/                 # Dockerfile + docker-compose.yml
```