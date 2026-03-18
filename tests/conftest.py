# tests/conftest.py
# =================
# PURPOSE: Shared pytest fixtures for the entire project.
# WHY THIS FILE EXISTS: It prevents code duplication by providing 
# a single 'async_client' that all tests can use.
# =================

from __future__ import annotations
from collections.abc import AsyncGenerator

import pytest   
import pytest_asyncio
from httpx import AsyncClient ,ASGITransport

from voice_commerce.main import create_app


@pytest.fixture(scope="session")
def app():
    """
    Create a FastAPI app instance for testing.
    This is the same as the one used in production, but we can override
    settings here if needed (e.g., use a test database).
    """
    return create_app()


@pytest_asyncio.fixture(scope="session")
async def async_client(app) -> AsyncGenerator[AsyncClient, None]:
    """
    Provide an AsyncClient for making HTTP requests to the FastAPI app during tests.
    Uses ASGITransport to directly call the app without needing a running server.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",   # base URL — all relative URLs resolve against this
    ) as client:
        yield client