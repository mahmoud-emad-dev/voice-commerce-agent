from __future__ import annotations

from httpx import AsyncClient

from voice_commerce.config.settings import settings
from voice_commerce.core.tools.tool_dispatcher import ToolContext, execute


async def test_metrics_endpoint_is_open_in_local_debug(async_client: AsyncClient) -> None:
    response = await async_client.get("/metrics")

    assert response.status_code == 200
    assert "voice_app_info" in response.text


async def test_metrics_endpoint_requires_admin_key_when_not_debug(
    async_client: AsyncClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "app_debug", False)
    monkeypatch.setattr(settings, "metrics_require_admin_key", True)

    response = await async_client.get("/metrics")

    assert response.status_code == 401


async def test_metrics_endpoint_allows_admin_key_when_not_debug(
    async_client: AsyncClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "app_debug", False)
    monkeypatch.setattr(settings, "metrics_require_admin_key", True)

    response = await async_client.get(
        "/metrics",
        headers={"X-Admin-Key": settings.admin_api_key},
    )

    assert response.status_code == 200
    assert "voice_ready_state" in response.text


async def test_metrics_endpoint_returns_404_when_disabled(
    async_client: AsyncClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", False)

    response = await async_client.get("/metrics")

    assert response.status_code == 404


async def test_metrics_include_tool_metrics_after_tool_execution(async_client: AsyncClient) -> None:
    await execute("show_cart", {}, ToolContext(session_id="metrics-test", tenant_id="demo"))

    response = await async_client.get("/metrics")

    assert response.status_code == 200
    assert "voice_tool_calls_total" in response.text
    assert "voice_tool_call_duration_seconds" in response.text
    assert 'tool_name="show_cart"' in response.text
