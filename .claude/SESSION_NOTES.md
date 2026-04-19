# Voice Commerce Agent — Session Context (April 15 2026)

## Project
- **Repo**: `P:\AI_Empire\Projects\voice-commerce-agent`
- **Phase**: 10 (demo polish) on branch `feature/phase-10-improve-fix-make_demo`
- **Stack**: FastAPI + Gemini Live API (native audio) + WooCommerce/CSV + Qdrant RAG + widget.js IIFE
- **Run**: `uv run uvicorn src.voice_commerce.main:app --reload --port 8000`

---

## What Was Done This Session (Phase 1 — COMPLETE)

### 1. `src/voice_commerce/config/settings.py`
Added 3 store identity fields in STORE SETTINGS block:
```python
store_name: str = "NEXFIT"
assistant_name: str = "PHOENIX"
store_tagline: str = "Your go-to store for performance sports gear."

### 2. `src/voice_commerce/core/voice/prompts.py` (NEW FILE — created by user)
- 11 prompt sections using `{assistant_name}`, `{store_name}`, `{store_tagline}`, `{category_list}`, `{category_summary_text}` placeholders
- Key functions: `build_prompt_sections()`, `build_system_prompt()`, `render_system_prompt()`, `append_conversation_history()`
- `_derive_category_list()` extracts category names from summary text as fallback

### 3. `src/voice_commerce/services/rag_service.py` (MASSIVELY EXPANDED)
- `_parse_category_path(raw_name)` — handles "Men > Shoes > Running" → dict of {full_path, main, sub, leaf}
- `_build_category_indexes(products)` — called in `sync_catalog()` step 1.5, builds category summary dict (count, min/max price, examples)
- `category_summary` property — safe read access
- `list_categories()` — sorted by product count
- `get_products_for_category()` — deterministic retrieval helper

### 4. `src/voice_commerce/core/voice/gemini_live_handler.py` (MODIFIED)
- Removed 100-line hardcoded prompt blob
- `__init__` now gets `category_summary` from `get_rag_service()`
- `_format_category_summary_text()` static method formats dict → "- Category | N products | $X–$Y | examples" lines
- `_build_system_prompt()` calls `prompts.build_system_prompt(...)` with all 5 values from settings + formatted category text
- Fixed `time` variable shadowing → renamed to `updated_at`

---

## Phase 1 Cleanup Still Needed (3 small fixes)

| Fix | File | What |
|-----|------|------|
| Move `_format_category_summary_text()` | `gemini_live_handler.py` → `prompts.py` | Prompt logic belongs in prompts module |
| Log slice | `gemini_live_handler.py` | `preview=system_prompt[:200]` (was `[:]`) |
| Log slice | `rag_service.py` | `top_categories=sorted(summary.keys())[:10]` (was `[:]`) |
| Persona lock | `prompts.py` HARD_LIMITS section | Add: `"- You are {assistant_name}. Never claim to be a different AI, never name your underlying model."` |

---

## Phase 2 — Snippets Provided, NOT YET IMPLEMENTED

### 2A — Cart Backend Bug Fixes
**Files**: `cart_tools.py`, `tool_registry.py`
- `cart_tools.py` line 74: `= quantity` → `+= quantity` (update was overwriting instead of adding)
- `cart_tools.py` lines 137–138: empty cart response was `ToolResponse.success(plain_string)` — no `data` dict → badge showed 1. Fix:
```
```python
return ToolResponse.success(
ai_text=f"Removed {name}. Your cart is now empty.",
data={"cart_count": 0, "product_id": product_id, "product_name": name},
)
- `tool_registry.py` `ADD_TO_CART_TOOL`: add explicit "Never guess product_id, use integer from search results" to description

### 2B — Audio Latency Fix (~1s saved)
**File**: `voice_websocket_handler.py`
- Remove 64-byte audio drop filter (lines 189–192) — was clipping speech starts
- Refactor text message handler to properly handle `audio_end` + `context_update` cases without 3 duplicate log calls

### 2C — Real Cart Sync (biggest demo bug)
**Files**: `browser_actions.py`, `action_dispatcher.py`, `widget.js`, `embed_demo.html`
- New `AddToRealCart` Pydantic action model
- `_on_add_to_cart` emits this new action
- `widget.js _doAddToRealCart()`: dispatches `vc:addToCart` custom event + WooCommerce AJAX `/?wc-ajax=add_to_cart`
- `embed_demo.html`: listens to `vc:addToCart` and renders demo cart panel

### 2D — Toast Polish
**Files**: `widget.js`, `action_dispatcher.py`
- `TOAST_DURATIONS = { success: 2000, info: 1500, warning: 3500, error: 5000 }`
- `TOAST_MAX = 2` (drop oldest when exceeded)
- Shorter strings: `"✓ {name} added"` / `"✕ {name} removed"`

### 2E — Product Modal Fix
**Files**: `browser_actions.py`, `action_dispatcher.py`, `widget.js`
- `ShowProductModal` gets `delay_ms: int = 0` and `product_data: dict | None = None` fields
- `_on_get_product_details` extracts thumbnail/price/short_desc/category from tool result and passes in action
- `_doShowProductModal` rewritten: image-on-top layout, category pill, "Add to Cart" button (bypasses Gemini, instant AJAX)

### 2F — Modal Animation Timing
**File**: `widget.js`
- `show_product_modal` case in `_onAction`: wrap `_doShowProductModal` in `setTimeout(delay_ms)` so highlight + modal don't collide

---

## Architecture Reminders

- **Single-file isolation**: `google.genai` only in `gemini_live_handler.py`
- **`session_id`** always injected by `tool_dispatcher.py` — tools scope cart state per session
- **Shadow cart** (`_CARTS` dict) = conversation context only; `AddToRealCart` action = actual WooCommerce cart sync
- **`product_data` locality**: product images/price live on server (CSV), not in DOM — pass in action payload, don't scrape
- **System prompt**: called once at session init in `_build_session_config()` → `_build_system_prompt()` → `prompts.build_system_prompt()`
- **Commit rule**: each Phase 2 part is self-contained → commit after each part

---

## Next Session Start Order

1. Phase 1 cleanup (4 small fixes above)
2. Phase 2A → commit
3. Phase 2B → commit
4. Phase 2C → commit
5. Phase 2D → commit
6. Phase 2E + 2F → commit