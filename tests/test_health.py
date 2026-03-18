# tests/test_health.py
# ====================
# PURPOSE: Verify the /health and /ready endpoints work.
# WHY THIS FILE EXISTS: To ensure the 'plumbing' (settings, routes, 
# and logging) is correctly wired before adding AI.
# ====================
from __future__ import annotations
 
import pytest
from httpx import AsyncClient

# @pytest.mark.asyncio
async def test_health_returns_200(async_client: AsyncClient) -> None:
    """
    Test that GET /health responds with HTTP 200 OK.
    """
    # Act: Make the request
    response = await async_client.get("/health")
    
  # Assert: check the status code
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}. "
        f"Response body: {response.text}"
    )

async def test_ready_returns_200_or_503(async_client: AsyncClient) -> None:
    """
    GET /ready should return either 200 (ready) or 503 (not ready).
 
    In tests, GEMINI_API_KEY may not be set, so we accept both status codes.
    What we DON'T accept: 404 (endpoint doesn't exist) or 500 (server error).
    """
    response = await async_client.get("/ready")
 
    assert response.status_code in (200, 503), (
        f"Expected 200 or 503, got {response.status_code}. "
        f"Response: {response.text}"
    )



# =============================================================================
# Error handling test
# =============================================================================
 
async def test_nonexistent_route_returns_404(async_client: AsyncClient) -> None:
    """
    Requests to non-existent routes should return 404, not 500.
 
    This verifies FastAPI's default error handling is in place.
    A 500 here would suggest something is very wrong with the app setup.
    """
    response = await async_client.get("/this-route-does-not-exist")
    assert response.status_code == 404