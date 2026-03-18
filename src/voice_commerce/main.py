# src/voice_commerce/main.py
# ===========================
# PURPOSE: The entry point and "App Factory" for the server.
# WHY THIS FILE EXISTS: It connects the settings, routes, and middleware 
# together into a single running FastAPI application.
# THIS FILE IN THE ARCHITECTURE: The central nervous system.
# ===========================


from __future__ import annotations
from contextlib import asynccontextmanager
import logging

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from srv.voice_commerce.config.settings import settings


log = structlog.get_logger(__name__)

@asynccontextmanager
async def lifespan():
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
    app = FastAPI()


    return app