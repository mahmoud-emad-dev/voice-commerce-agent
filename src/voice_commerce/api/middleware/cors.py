# src/voice_commerce/api/middleware/cors.py
# =============================================================================
# PURPOSE: Configures Cross-Origin Resource Sharing (CORS) for the FastAPI app.
# WHY THIS EXISTS: When widget.js runs on your WordPress site (e.g., http://localhost:8080)
# it needs permission to talk to this Python server (e.g., http://localhost:8000).
# =============================================================================
"""
api/middleware/cors.py
Phase 9 — CORS middleware update.
 
What changed from Phase 6?
--------------------------
We add  /widget.js  and  /embed_demo.html  to the paths that get
Access-Control-Allow-Origin: *  so any WooCommerce store can load the
widget script and the embed page in a cross-origin iframe for testing.
 
FastAPI's CORSMiddleware applies to ALL routes by default — but only for
requests that carry an Origin header.  The explicit headers in widget.py
handle the <script> tag case which browsers treat differently.
 
Why keep middleware AND per-route headers?
------------------------------------------
CORSMiddleware handles preflight OPTIONS requests from fetch()/XHR calls
(e.g., the WebSocket upgrade path, API calls the widget might make).
Per-route headers in widget.py handle the <script src> and <img src> cases
where browsers set Origin but expect the header on the response directly.
Keeping both is correct and not redundant.
"""
from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def add_cors_middleware(app: FastAPI) -> None:
    """
    Register CORS middleware on the FastAPI app.
 
    allow_origins=["*"]
        Allows any domain to call the API.  Fine for a portfolio project
        and for initial multi-tenant deployment where tenant stores connect.
        In a locked-down production setup you'd replace "*" with a list of
        registered tenant domains read from your database.
 
    allow_credentials=False
        Must be False when allow_origins=["*"].  Browsers block credentials
        (cookies, auth headers) on wildcard-origin responses.  Our widget
        uses API keys in the WS query string, not cookies.
 
    allow_methods / allow_headers
        Permissive for development.  Tighten in production.
    """
    # For local testing, we allow all origins. 
    # Before GitHub/Production, change this to your actual WordPress URL.

    allowed_origins = [
        "*", 
        # "http://localhost:8080",      # Example local WordPress
        # "https://my-real-store.com"   # Example production WordPress
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,  
        allow_credentials=False, 
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
        expose_headers=["Content-Type", "Content-Length"],
    )