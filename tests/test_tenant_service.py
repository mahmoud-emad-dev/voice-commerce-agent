from __future__ import annotations

import pytest

from voice_commerce.models.tenant import TenantCreateRequest
from voice_commerce.services.tenant_service import TenantResolutionError, TenantService


async def test_demo_tenant_is_available_without_startup() -> None:
    service = TenantService()

    tenant = await service.get_tenant("demo")

    assert tenant is not None
    assert tenant.tenant_id == "demo"
    assert tenant.is_active is True


async def test_create_tenant_and_resolve_with_api_key() -> None:
    service = TenantService()
    created = await service.create_tenant(
        TenantCreateRequest(
            tenant_id="store-two",
            display_name="Store Two",
            api_key="store-two-key",
            allowed_origins=["https://store-two.example"],
        )
    )

    resolved = await service.resolve_tenant(
        "store-two",
        "store-two-key",
        allow_demo_fallback=False,
    )

    assert created.tenant_id == "store-two"
    assert resolved.display_name == "Store Two"
    assert resolved.allowed_origins == ["https://store-two.example"]


async def test_invalid_tenant_key_raises_resolution_error() -> None:
    service = TenantService()
    await service.create_tenant(
        TenantCreateRequest(
            tenant_id="store-three",
            display_name="Store Three",
            api_key="right-key",
        )
    )

    with pytest.raises(TenantResolutionError):
        await service.resolve_tenant("store-three", "wrong-key", allow_demo_fallback=False)
