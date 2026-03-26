# src/voice_commerce/main.py
# ==============================================================================
# PURPOSE: The entry point and "App Factory" for the FastAPI server.
#
# WHY THIS FILE EXISTS: 
#   It connects settings, routers, and middleware into a single ASGI application.
#   We use a factory function (create_app) so we can easily create test instances
#   of the app during automated testing without starting the real server.
# ==============================================================================
# THIS FILE IN THE ARCHITECTURE: The central nervous system.
# # ==============================================================================



from __future__ import annotations
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any
import logging
import os

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


from voice_commerce.config.settings import settings
from voice_commerce.api.routes import health , voice
log = structlog.get_logger(__name__)


def configure_logging() -> None:
    """
    Configure structlog for structured JSON logging.
    Called once at application startup.
 
    The configuration chain:
    1. structlog.contextvars.merge_contextvars — adds any context variables
       (like tenant_id) that were bound with structlog.contextvars.bind_contextvars()
    2. structlog.stdlib.add_log_level — adds the "level" field to every log entry
    3. structlog.stdlib.add_logger_name — adds the "logger" field (which file logged it)
    4. structlog.processors.TimeStamper — adds ISO 8601 timestamp
    5. structlog.dev.ConsoleRenderer — pretty output in dev (JSON in production)
    """
    log_level = getattr(logging, settings.log_level, logging.INFO)
 
    structlog.configure(
        processors=[
            # Merge any contextvars (we'll use this in Phase 13 to auto-attach tenant_id)
            structlog.contextvars.merge_contextvars,
            # Add standard fields to every log entry
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            # In debug mode: pretty colored output for readability
            # In production: JSON output for machine parsing
            structlog.dev.ConsoleRenderer() if settings.app_debug
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
 
    # Also configure the standard library logging to the same level
    # (some libraries use stdlib logging directly)
    logging.basicConfig(level=log_level, format="%(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, Any]:
    # --- STARTUP ---
    log.info(
        "voice_commerce_agent_starting",
        port=settings.app_port,
        debug=settings.app_debug,
        model=settings.gemini_model
    )
    yield
    # --- SHUTDOWN ---
    log.info("Application shutting down")



def create_app() -> FastAPI:
    """
    Factory function to create and configure the FastAPI instance.
    """
    configure_logging()

    app = FastAPI(
        title="Voice Commerce Agent",
        description="An AI agent for voice commerce applications.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_debug else None,
        redoc_url="/redoc" if settings.app_debug else None,
    )

    # CORS Middleware: Allows the frontend browser to talk to this backend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Adjust this in production # Phase 14: Restrict this to real domain name
        allow_credentials=True, 
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Root route - provides a friendly entry point
    @app.get("/" , tags=["system"])
    async def root():
        """
        Root endpoint returning basic API metadata.
        """
        return {"message": "Welcome to the Voice Commerce Agent API", "version": "0.1.0"}
    # Register other routes 
    app.include_router(health.router ,tags=["system"])
    app.include_router(voice.router, prefix="/ws", tags=["voice"])

    # Mount the frontend UI folder so localhost:8000/static/test_client.html works
    static_dir = "static"
    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
 

    return app

# The actual global variable Uvicorn looks for to start the server
app = create_app()
