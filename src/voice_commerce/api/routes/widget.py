"""
api/routes/widget.py
Phase 9 — Serves widget.js and embed_demo.html with correct MIME types and
           cross-origin headers so any WooCommerce store can load the script.
 
Why a dedicated route for JS?
------------------------------
FastAPI's StaticFiles mounts serve files fine for same-origin requests,
but when a WooCommerce store at store.example.com loads
  <script src="https://your-server.com/widget.js">
the browser performs a CORS preflight check.
 
The server must respond with:
  Access-Control-Allow-Origin: *   (or the specific store origin)
  Content-Type: application/javascript
 
StaticFiles does NOT add CORS headers automatically — that's the app-level
CORSMiddleware's job, and it only fires on API routes unless you configure
it to match static paths too.
 
Using an explicit route here gives us precise control over headers and
lets us add per-tenant logic later (e.g., only serve to authorised origins).
 
Route structure
---------------
GET /widget.js          → the IIFE script (loaded by <script src=...>)
GET /embed_demo.html    → the simulated WooCommerce store page (dev only)
GET /widget/health      → sanity check
"""
# src/voice_commerce/api/routes/widget.py
# =============================================================================
# PURPOSE: Serves widget.js and pcm-processor.js with explicit CORS headers.
# WHY THIS EXISTS: FastAPI's StaticFiles mount often bypasses CORSMiddleware. 
# Because AudioWorklet (pcm-processor.js) strictly requires CORS to load cross-domain,
# we must serve these files manually with explicit Access-Control headers.
# =============================================================================

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter , Request , HTTPException 
from fastapi.responses import FileResponse , JSONResponse , HTMLResponse



# Locate the static directory relative to this file
#   api/routes/widget.py  →  ../../static/
_STATIC_DIR = Path(__file__).resolve().parents[4] / "static"

router = APIRouter(tags=["widget"])


# ── CORS helper ──────────────────────────────────────────────────────────────
def _cors_headers(origin: str | None = None) -> dict:
    """Return explicit CORS headers for cross-origin script loading."""
    return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Cross-Origin-Resource-Policy": "cross-origin",  # Crucial for Chrome security
        }

# ── Routes ────────────────────────────────────────────────────────────────────
@router.options("/widget.js")
async def widget_js_preflight(request: Request) -> JSONResponse:
    """Handle CORS preflight for script loads."""
    return JSONResponse(
        content={},
        headers=_cors_headers(request.headers.get("origin")),
    )

@router.get("/widget.js")
async def serve_widget_js_file(request: Request) -> FileResponse:
    """
    Serve our specific JavaScript files with hardcoded CORS headers.
    This guarantees WordPress can download the AudioWorklet processor.
    """
    path = _STATIC_DIR / "widget.js"
    if not path.exists():
        raise HTTPException(status_code=404, detail="widget.js not found")

    return FileResponse(
        path=path,
        media_type="application/javascript",
        headers={
            **_cors_headers(request.headers.get("origin")),
            # Tell browsers to cache the file for 5 minutes in dev.
            # In production, set a longer max-age and add a content hash to
            # the filename for cache busting: widget.abc123.js
            "Cache-Control": "public, max-age=300",
        },
    )

@router.get("/embed_demo.html", response_class=HTMLResponse)
async def serve_embed_demo(request: Request) -> FileResponse:
    """
    Serve the demo WooCommerce store page.
 
    This is a development tool — shows exactly what a store owner's page
    looks like once they've dropped in the single <script> tag.
 
    In production this endpoint would be removed (or gated behind auth).
    """
    path = _STATIC_DIR / "embed_demo.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="embed_demo.html not found")
 
    return FileResponse(
        path=path,
        media_type="text/html",
        headers={"Cache-Control": "no-store"},  # always fresh during dev

    )

@router.get("/health/check")
async def widget_health() -> JSONResponse:
    """Quick sanity check to confirm static files exist."""
    widget_exists = (_STATIC_DIR / "widget.js").exists()
    return JSONResponse({
        "status": "ok" if widget_exists else "degraded",
        "widget_js": widget_exists,
        "static_dir":    str(_STATIC_DIR),

    })

if __name__ == "__main__":
    print(_STATIC_DIR)