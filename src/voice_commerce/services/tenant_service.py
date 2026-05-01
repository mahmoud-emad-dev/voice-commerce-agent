from __future__ import annotations

import hashlib
import hmac
import json

import asyncpg
import structlog

from voice_commerce.config.settings import settings
from voice_commerce.models.tenant import Tenant, TenantCreateRequest

log = structlog.get_logger(__name__)


class TenantResolutionError(Exception):
    """Raised when tenant identity cannot be resolved safely."""


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(str(raw_key or "").encode("utf-8")).hexdigest()


def _default_collection_name(tenant_id: str) -> str:
    return f"catalog_{tenant_id}"


def _demo_tenant() -> Tenant:
    tenant_id = settings.demo_tenant_id
    return Tenant(
        tenant_id=tenant_id,
        display_name=settings.demo_tenant_name,
        allowed_origins=list(settings.demo_tenant_allowed_origins),
        qdrant_collection=_default_collection_name(tenant_id),
        status="active",
        api_key_hash=_hash_api_key(settings.demo_tenant_api_key),
    )


class TenantService:
    """Small tenant registry with Postgres persistence and demo fallback."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self._memory: dict[str, Tenant] = {}

    @property
    def enabled(self) -> bool:
        return settings.tenant_mode.strip().lower() != "off"

    @property
    def use_database(self) -> bool:
        return settings.postgres_enabled

    def _ensure_demo_tenant_loaded(self) -> None:
        self._memory.setdefault(settings.demo_tenant_id, _demo_tenant())

    async def initialize(self) -> None:
        if not self.enabled:
            log.info("tenant_service_disabled")
            return

        self._ensure_demo_tenant_loaded()
        if not self.use_database:
            log.info("tenant_service_ready_in_memory", tenant_count=len(self._memory))
            return

        self._pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=5)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    allowed_origins JSONB NOT NULL DEFAULT '[]'::jsonb,
                    qdrant_collection TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    api_key_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            demo = _demo_tenant()
            await conn.execute(
                """
                INSERT INTO tenants (
                    tenant_id,
                    display_name,
                    allowed_origins,
                    qdrant_collection,
                    status,
                    api_key_hash,
                    created_at,
                    updated_at
                )
                VALUES ($1, $2, $3::jsonb, $4, $5, $6, NOW(), NOW())
                ON CONFLICT (tenant_id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    allowed_origins = EXCLUDED.allowed_origins,
                    qdrant_collection = EXCLUDED.qdrant_collection,
                    status = EXCLUDED.status,
                    api_key_hash = EXCLUDED.api_key_hash,
                    updated_at = NOW()
                """,
                demo.tenant_id,
                demo.display_name,
                json.dumps(demo.allowed_origins),
                demo.qdrant_collection,
                demo.status,
                demo.api_key_hash,
            )
        log.info("tenant_service_ready", mode=settings.tenant_mode, db_enabled=self.use_database)

    async def shutdown(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
        self._memory.clear()
        log.info("tenant_service_closed")

    async def get_tenant(self, tenant_id: str) -> Tenant | None:
        tenant_id = str(tenant_id or "").strip()
        if not tenant_id:
            return None
        self._ensure_demo_tenant_loaded()
        if not self.use_database or self._pool is None:
            return self._memory.get(tenant_id)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    tenant_id,
                    display_name,
                    allowed_origins::text AS allowed_origins_json,
                    qdrant_collection,
                    status,
                    api_key_hash,
                    created_at::text AS created_at,
                    updated_at::text AS updated_at
                FROM tenants
                WHERE tenant_id = $1
                """,
                tenant_id,
            )
        if row is None:
            return None
        return Tenant(
            tenant_id=row["tenant_id"],
            display_name=row["display_name"],
            allowed_origins=json.loads(row["allowed_origins_json"] or "[]"),
            qdrant_collection=row["qdrant_collection"],
            status=row["status"],
            api_key_hash=row["api_key_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def list_tenants(self) -> list[Tenant]:
        self._ensure_demo_tenant_loaded()
        if not self.use_database or self._pool is None:
            return sorted(self._memory.values(), key=lambda tenant: tenant.tenant_id)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    tenant_id,
                    display_name,
                    allowed_origins::text AS allowed_origins_json,
                    qdrant_collection,
                    status,
                    api_key_hash,
                    created_at::text AS created_at,
                    updated_at::text AS updated_at
                FROM tenants
                ORDER BY tenant_id
                """
            )
        return [
            Tenant(
                tenant_id=row["tenant_id"],
                display_name=row["display_name"],
                allowed_origins=json.loads(row["allowed_origins_json"] or "[]"),
                qdrant_collection=row["qdrant_collection"],
                status=row["status"],
                api_key_hash=row["api_key_hash"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def create_tenant(self, payload: TenantCreateRequest) -> Tenant:
        tenant = Tenant(
            tenant_id=payload.tenant_id.strip(),
            display_name=payload.display_name.strip(),
            allowed_origins=list(payload.allowed_origins),
            qdrant_collection=(
                payload.qdrant_collection or _default_collection_name(payload.tenant_id)
            ),
            status="active",
            api_key_hash=_hash_api_key(payload.api_key),
        )
        if not self.use_database or self._pool is None:
            self._memory[tenant.tenant_id] = tenant
            return tenant

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tenants (
                    tenant_id,
                    display_name,
                    allowed_origins,
                    qdrant_collection,
                    status,
                    api_key_hash,
                    created_at,
                    updated_at
                )
                VALUES ($1, $2, $3::jsonb, $4, $5, $6, NOW(), NOW())
                ON CONFLICT (tenant_id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    allowed_origins = EXCLUDED.allowed_origins,
                    qdrant_collection = EXCLUDED.qdrant_collection,
                    status = EXCLUDED.status,
                    api_key_hash = EXCLUDED.api_key_hash,
                    updated_at = NOW()
                """,
                tenant.tenant_id,
                tenant.display_name,
                json.dumps(tenant.allowed_origins),
                tenant.qdrant_collection,
                tenant.status,
                tenant.api_key_hash,
            )
        return tenant

    async def disable_tenant(self, tenant_id: str) -> Tenant | None:
        tenant = await self.get_tenant(tenant_id)
        if tenant is None:
            return None
        tenant.status = "disabled"
        tenant.touch()
        if not self.use_database or self._pool is None:
            self._memory[tenant.tenant_id] = tenant
            return tenant

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE tenants
                SET status = $2, updated_at = NOW()
                WHERE tenant_id = $1
                """,
                tenant.tenant_id,
                tenant.status,
            )
        return tenant

    async def resolve_tenant(
        self,
        tenant_id: str | None,
        tenant_key: str | None,
        *,
        allow_demo_fallback: bool,
    ) -> Tenant:
        resolved_tenant_id = str(tenant_id or "").strip()
        resolved_tenant_key = str(tenant_key or "").strip()

        if not resolved_tenant_id and allow_demo_fallback:
            resolved_tenant_id = settings.demo_tenant_id
            resolved_tenant_key = settings.demo_tenant_api_key

        tenant = await self.get_tenant(resolved_tenant_id)
        if tenant is None:
            raise TenantResolutionError("Unknown tenant.")
        if not tenant.is_active:
            raise TenantResolutionError("Tenant is disabled.")

        expected_hash = tenant.api_key_hash
        provided_hash = _hash_api_key(resolved_tenant_key)
        if expected_hash and not hmac.compare_digest(expected_hash, provided_hash):
            raise TenantResolutionError("Tenant key is invalid.")
        return tenant


_tenant_service_instance: TenantService | None = None


def get_tenant_service() -> TenantService:
    global _tenant_service_instance
    if _tenant_service_instance is None:
        _tenant_service_instance = TenantService()
    return _tenant_service_instance


async def initialize_tenant_service() -> TenantService:
    service = get_tenant_service()
    await service.initialize()
    return service


async def shutdown_tenant_service() -> None:
    service = get_tenant_service()
    await service.shutdown()
