from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TenantStatus = Literal["active", "disabled"]


class Tenant(BaseModel):
    """Tenant configuration used to isolate one storefront from another."""

    tenant_id: str
    display_name: str
    allowed_origins: list[str] = Field(default_factory=list)
    catalog_source: str = "csv"
    catalog_path: str
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
    catalog_source: str = "csv"
    catalog_path: str | None = None
    qdrant_collection: str | None = None

    @field_validator("catalog_source")
    @classmethod
    def validate_catalog_source(cls, value: str) -> str:
        normalized = str(value or "csv").strip().lower()
        if normalized != "csv":
            raise ValueError("Only csv catalog_source is supported in Phase 12.")
        return normalized

    @field_validator("catalog_path")
    @classmethod
    def validate_catalog_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        if not normalized.lower().endswith(".csv"):
            raise ValueError("catalog_path must point to a CSV file.")
        return normalized


class TenantPublic(BaseModel):
    """Safe public tenant shape that omits sensitive fields."""

    tenant_id: str
    display_name: str
    allowed_origins: list[str] = Field(default_factory=list)
    catalog_source: str
    catalog_path: str
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
        catalog_source=tenant.catalog_source,
        catalog_path=tenant.catalog_path,
        qdrant_collection=tenant.qdrant_collection,
        status=tenant.status,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
    )
