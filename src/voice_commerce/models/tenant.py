from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

TenantStatus = Literal["active", "disabled"]


class Tenant(BaseModel):
    """Tenant configuration used to isolate one storefront from another."""

    tenant_id: str
    display_name: str
    allowed_origins: list[str] = Field(default_factory=list)
    qdrant_collection: str
    status: TenantStatus = "active"
    api_key_hash: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def is_active(self) -> bool:
        """True when this tenant is allowed to use the app."""
        return self.status == "active"

    def touch(self) -> None:
        """Refresh the updated timestamp after any tenant change."""
        self.updated_at = datetime.now(UTC).isoformat()


class TenantCreateRequest(BaseModel):
    """Admin request body for creating one tenant."""

    tenant_id: str
    display_name: str
    api_key: str
    allowed_origins: list[str] = Field(default_factory=list)
    qdrant_collection: str | None = None


class TenantPublic(BaseModel):
    """Safe public tenant shape that omits sensitive fields."""

    tenant_id: str
    display_name: str
    allowed_origins: list[str] = Field(default_factory=list)
    qdrant_collection: str
    status: TenantStatus
    created_at: str
    updated_at: str


def to_public_tenant(tenant: Tenant) -> TenantPublic:
    """Strip sensitive fields before returning tenant details from APIs."""
    return TenantPublic(
        tenant_id=tenant.tenant_id,
        display_name=tenant.display_name,
        allowed_origins=list(tenant.allowed_origins),
        qdrant_collection=tenant.qdrant_collection,
        status=tenant.status,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
    )
