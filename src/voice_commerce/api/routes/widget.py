"""Serve widget assets with explicit cross-origin headers.

These files are loaded directly by external storefront pages, so we keep them
on dedicated routes instead of relying on a generic static mount.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from voice_commerce.config.settings import settings

_STATIC_DIR = Path(__file__).resolve().parents[4] / "static"

router = APIRouter(tags=["widget"])


# ── CORS helper ──────────────────────────────────────────────────────────────
def _cors_headers(origin: str | None = None) -> dict[str, str]:
    """Return explicit CORS headers for cross-origin script loading."""
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Cross-Origin-Resource-Policy": "cross-origin",
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
    Serve the embeddable widget bundle with explicit CORS headers.

    Keeping this as a route gives us predictable headers for storefront script
    tags and leaves room for tenant-level rules later.
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
    Serve the demo storefront page used during local development.

    This stays behind the public-demo flag so the production deploy can omit it.
    """
    if not settings.is_public_demo_enabled:
        raise HTTPException(status_code=404, detail="embed_demo.html not available")

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
    return JSONResponse(
        {
            "status": "ok" if widget_exists else "degraded",
            "widget_js": widget_exists,
            "static_dir": str(_STATIC_DIR),
        }
    )
