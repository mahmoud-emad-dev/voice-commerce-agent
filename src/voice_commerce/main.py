"""Application entry point and FastAPI app factory."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI

from voice_commerce.api.middleware.cors import add_cors_middleware
from voice_commerce.api.routes import admin, health, metrics, voice, widget
from voice_commerce.config.settings import settings
from voice_commerce.core.rag import embedder
from voice_commerce.observability.logging import configure_logging
from voice_commerce.observability.metrics import (
    STARTUP_DURATION,
    initialize_base_metrics,
    observe_startup_step,
)
from voice_commerce.services.rag_service import get_rag_service
from voice_commerce.services.session_state_store import (
    initialize_session_state_store,
    shutdown_session_state_store,
)
from voice_commerce.services.tenant_service import (
    initialize_tenant_service,
    shutdown_tenant_service,
)

log = structlog.get_logger(__name__)


async def _warm_rag_pipeline() -> None:
    """Warm the embedder and then sync the catalog without blocking app startup."""
    rag = get_rag_service()
    try:
        embedder_started_at = time.perf_counter()
        await embedder.warmup()
        observe_startup_step(
            "embedder_warmup",
            time.perf_counter() - embedder_started_at,
            status="success",
        )
        log.info("app_startup_embedder_warmed")

        rag_sync_started_at = time.perf_counter()
        indexed = await rag.sync_catalog()
        observe_startup_step(
            "rag_catalog_sync",
            time.perf_counter() - rag_sync_started_at,
            status="success",
        )
        log.info("app_startup_rag_catalog_sync_finished", indexed=indexed)
    except Exception as exc:
        observe_startup_step("rag_pipeline", 0.0, status="error")
        log.exception("app_startup_rag_pipeline_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, Any]:
    """Manage startup and shutdown resources for the FastAPI application."""
    # --- STARTUP ---
    startup_started_at = time.perf_counter()
    log.info(
        "voice_commerce_agent_starting",
        port=settings.app_port,
        debug=settings.app_debug,
        model=settings.gemini_model,
        woocommerce_configured=settings.is_woocommerce_configured,
    )

    # Current phases boot from the demo CSV catalog so the static demo pages
    # work reliably without a live store dependency.
    #
    # Real-store path kept intentionally for reference:
    #   1. initialize the WooCommerce client
    #   2. store it on app.state
    #   3. sync the RAG catalog from the live store
    #
    # That WooCommerce integration already exists in the codebase, but for the
    # current demo phases we start from the CSV catalog to keep the static demo
    # pages reproducible and independent from a live storefront.
    from voice_commerce.services import csv_client

    csv_started_at = time.perf_counter()
    store_client = await csv_client.initialize(settings.demo_tenant_catalog_path)
    observe_startup_step(
        "csv_client_initialize",
        time.perf_counter() - csv_started_at,
        status="success",
    )
    app.state.store_client = store_client
    log.info("app_startup_csv_store_connected")

    session_store_started_at = time.perf_counter()
    await initialize_session_state_store()
    observe_startup_step(
        "session_state_store_initialize",
        time.perf_counter() - session_store_started_at,
        status="success",
    )
    log.info("app_startup_session_state_store_initialized", enabled=settings.postgres_enabled)

    tenant_service_started_at = time.perf_counter()
    await initialize_tenant_service()
    observe_startup_step(
        "tenant_service_initialize",
        time.perf_counter() - tenant_service_started_at,
        status="success",
    )
    log.info("app_startup_tenant_service_initialized", mode=settings.tenant_mode)

    # Warm the demo catalog in the background so semantic search is ready soon
    # after startup without blocking the server boot sequence.
    get_rag_service()
    asyncio.create_task(_warm_rag_pipeline())
    log.info("app_startup_rag_service_initialized")
    STARTUP_DURATION.observe(time.perf_counter() - startup_started_at)

    yield

    # --- SHUTDOWN ---
    log.info("Application  shutting down...")

    await csv_client.shutdown()
    log.info("app_shutdown_csv_store_disconnected")

    await shutdown_session_state_store()
    log.info("app_shutdown_session_state_store_closed")
    await shutdown_tenant_service()
    log.info("app_shutdown_tenant_service_closed")

    log.info("Application  shut down completed")


def create_app() -> FastAPI:
    """
    Factory function to create and configure the FastAPI instance.
    """
    configure_logging()
    initialize_base_metrics()

    app = FastAPI(
        title="Voice Commerce Agent",
        description="An AI agent for voice commerce applications.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_debug else None,
        redoc_url="/redoc" if settings.app_debug else None,
    )

    # CORS Middleware: Allows the frontend browser to talk to this backend
    add_cors_middleware(app)

    # Root route - provides a friendly entry point
    @app.get("/", tags=["system"])
    async def root():
        """
        Root endpoint returning basic API metadata.
        """
        return {"message": "Welcome to the Voice Commerce Agent API", "version": "0.1.0"}

    # Lightweight runtime endpoint to confirm the background catalog sync state.
    @app.get("/rag/stats", tags=["system"])
    async def rag_stats():
        """Check if the background RAG sync has finished."""
        rag = get_rag_service()
        return rag.stats()

    # Register other routes
    app.include_router(health.router, tags=["system"])
    app.include_router(metrics.router, tags=["system"])
    app.include_router(admin.router, prefix="/admin", tags=["admin"])
    app.include_router(voice.router, prefix="/ws", tags=["voice"])
    app.include_router(widget.router, prefix="/static", tags=["widget"])

    return app


app = create_app()
