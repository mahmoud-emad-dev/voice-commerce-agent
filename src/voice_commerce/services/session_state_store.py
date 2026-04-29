from __future__ import annotations

import json
from typing import Any, TypedDict

import asyncpg
import structlog

from voice_commerce.config.settings import settings

log = structlog.get_logger(__name__)


class PersistedSessionState(TypedDict):
    session_id: str
    transcript: list[dict[str, str]]
    resumption_handle: str | None
    cart: dict[str, Any]
    checkout: dict[str, Any] | None


class SessionStateStore:
    """Small Postgres-backed store for session transcript, cart, and checkout state."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    @property
    def enabled(self) -> bool:
        """True when Postgres-backed persistence is enabled."""
        return settings.postgres_enabled

    @property
    def is_ready(self) -> bool:
        """True when the store is usable, or intentionally disabled."""
        return not self.enabled or self._pool is not None

    async def initialize(self) -> None:
        """Connect to Postgres and create the session_state table if needed."""
        if not self.enabled:
            log.info("session_state_store_disabled")
            return

        self._pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=5)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_state (
                    session_id TEXT PRIMARY KEY,
                    transcript JSONB NOT NULL DEFAULT '[]'::jsonb,
                    resumption_handle TEXT,
                    cart JSONB NOT NULL DEFAULT '{}'::jsonb,
                    checkout JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        log.info("session_state_store_ready", host=settings.postgres_host, db=settings.postgres_db)

    async def shutdown(self) -> None:
        """Close the Postgres pool during app shutdown."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            log.info("session_state_store_closed")

    async def load_session(self, session_id: str) -> PersistedSessionState | None:
        """Load one saved session snapshot by session_id."""
        if not self.enabled or self._pool is None:
            return None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    session_id,
                    transcript::text AS transcript_json,
                    resumption_handle,
                    cart::text AS cart_json,
                    checkout::text AS checkout_json
                FROM session_state
                WHERE session_id = $1
                """,
                session_id,
            )

        if row is None:
            return None

        transcript_raw = row["transcript_json"] or "[]"
        cart_raw = row["cart_json"] or "{}"
        checkout_raw = row["checkout_json"]
        return {
            "session_id": row["session_id"],
            "transcript": json.loads(transcript_raw),
            "resumption_handle": row["resumption_handle"],
            "cart": json.loads(cart_raw),
            "checkout": json.loads(checkout_raw) if checkout_raw else None,
        }

    async def save_session(
        self,
        session_id: str,
        *,
        transcript: list[dict[str, str]],
        resumption_handle: str | None,
        cart: dict[str, Any],
        checkout: dict[str, Any] | None,
    ) -> None:
        """Insert or update the full saved snapshot for one session."""
        if not self.enabled or self._pool is None:
            return

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO session_state (
                    session_id,
                    transcript,
                    resumption_handle,
                    cart,
                    checkout,
                    created_at,
                    updated_at
                )
                VALUES ($1, $2::jsonb, $3, $4::jsonb, $5::jsonb, NOW(), NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    transcript = EXCLUDED.transcript,
                    resumption_handle = EXCLUDED.resumption_handle,
                    cart = EXCLUDED.cart,
                    checkout = EXCLUDED.checkout,
                    updated_at = NOW()
                """,
                session_id,
                json.dumps(transcript),
                resumption_handle,
                json.dumps(cart),
                json.dumps(checkout),
            )


_store_instance: SessionStateStore | None = None


def get_session_state_store() -> SessionStateStore:
    """Return the process-wide session-state store singleton."""
    global _store_instance
    if _store_instance is None:
        _store_instance = SessionStateStore()
    return _store_instance


async def initialize_session_state_store() -> SessionStateStore:
    """Initialize the process-wide session-state store."""
    store = get_session_state_store()
    await store.initialize()
    return store


async def shutdown_session_state_store() -> None:
    """Close the process-wide session-state store."""
    store = get_session_state_store()
    await store.shutdown()
