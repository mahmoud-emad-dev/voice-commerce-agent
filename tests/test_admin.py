from __future__ import annotations

from httpx import AsyncClient

from voice_commerce.models.tenant import Tenant, TenantCreateRequest


class FakeTenantService:
    def __init__(self) -> None:
        self.tenants: dict[str, Tenant] = {
            "demo": Tenant(
                tenant_id="demo",
                display_name="NEXFIT Demo",
                allowed_origins=["*"],
                qdrant_collection="catalog_demo",
                status="active",
                api_key_hash="hash",
            )
        }

    async def list_tenants(self) -> list[Tenant]:
        return list(self.tenants.values())

    async def create_tenant(self, payload: TenantCreateRequest) -> Tenant:
        tenant = Tenant(
            tenant_id=payload.tenant_id,
            display_name=payload.display_name,
            allowed_origins=list(payload.allowed_origins),
            qdrant_collection=payload.qdrant_collection or f"catalog_{payload.tenant_id}",
            status="active",
            api_key_hash="hashed",
        )
        self.tenants[tenant.tenant_id] = tenant
        return tenant

    async def disable_tenant(self, tenant_id: str) -> Tenant | None:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            return None
        tenant.status = "disabled"
        return tenant


async def test_admin_requires_api_key(async_client: AsyncClient) -> None:
    response = await async_client.get("/admin/tenants")

    assert response.status_code == 401


async def test_admin_can_list_create_and_disable_tenants(
    async_client: AsyncClient,
    monkeypatch,
) -> None:
    service = FakeTenantService()
    monkeypatch.setattr("voice_commerce.api.routes.admin.get_tenant_service", lambda: service)

    headers = {"X-Admin-Key": "dev-admin-key"}
    list_response = await async_client.get("/admin/tenants", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()["tenants"][0]["tenant_id"] == "demo"

    create_response = await async_client.post(
        "/admin/tenants",
        headers=headers,
        json={
            "tenant_id": "store-four",
            "display_name": "Store Four",
            "api_key": "store-four-key",
            "allowed_origins": ["https://store-four.example"],
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["tenant"]["tenant_id"] == "store-four"

    disable_response = await async_client.patch(
        "/admin/tenants/store-four/disable",
        headers=headers,
    )
    assert disable_response.status_code == 200
    assert disable_response.json()["tenant"]["status"] == "disabled"
