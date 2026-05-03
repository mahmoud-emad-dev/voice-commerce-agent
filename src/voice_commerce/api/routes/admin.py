from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from voice_commerce.config.settings import settings
from voice_commerce.models.tenant import TenantCreateRequest, to_public_tenant
from voice_commerce.services.tenant_service import get_tenant_service

router = APIRouter()


def _require_admin_key(x_admin_key: str | None) -> None:
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")


@router.get("/tenants")
async def list_tenants(x_admin_key: str | None = Header(default=None)) -> dict[str, list[dict]]:
    _require_admin_key(x_admin_key)
    tenants = await get_tenant_service().list_tenants()
    return {"tenants": [to_public_tenant(tenant).model_dump() for tenant in tenants]}


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreateRequest,
    x_admin_key: str | None = Header(default=None),
) -> dict[str, dict]:
    _require_admin_key(x_admin_key)
    tenant = await get_tenant_service().create_tenant(payload)
    return {"tenant": to_public_tenant(tenant).model_dump()}


@router.patch("/tenants/{tenant_id}/disable")
async def disable_tenant(
    tenant_id: str,
    x_admin_key: str | None = Header(default=None),
) -> dict[str, dict]:
    _require_admin_key(x_admin_key)
    tenant = await get_tenant_service().disable_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return {"tenant": to_public_tenant(tenant).model_dump()}
