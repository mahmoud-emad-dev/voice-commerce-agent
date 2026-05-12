from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

CheckoutStep = Literal["review", "shipping", "payment", "confirm", "success", "cancelled"]
ShippingOption = Literal["standard", "express"]
PaymentOption = Literal["card", "paypal"]


@dataclass
class CheckoutState:
    """Mutable in-memory snapshot for one demo checkout session."""

    session_id: str
    step: CheckoutStep = "review"
    profile_id: str = "default_demo"
    shipping: ShippingOption | None = None
    payment: PaymentOption | None = None
    totals: dict[str, float] = field(default_factory=dict)
    cart_snapshot: list[dict] = field(default_factory=list)
    order_id: str | None = None
    last_updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def is_open(self) -> bool:
        """True while the checkout can still be updated by the user."""
        return self.step not in {"success", "cancelled"}

    def touch(self) -> None:
        """Refresh the timestamp whenever the checkout state changes."""
        self.last_updated_at = datetime.now(UTC).isoformat()


_CHECKOUTS: dict[str, CheckoutState] = {}


def _scoped_session_key(session_id: str, tenant_id: str | None = None) -> str:
    return f"{tenant_id or 'demo'}:{session_id}"


def get_checkout(session_id: str, tenant_id: str | None = None) -> CheckoutState | None:
    return _CHECKOUTS.get(_scoped_session_key(session_id, tenant_id))


def set_checkout(state: CheckoutState, tenant_id: str | None = None) -> CheckoutState:
    state.touch()
    _CHECKOUTS[_scoped_session_key(state.session_id, tenant_id)] = state
    return state


def clear_checkout(session_id: str, tenant_id: str | None = None) -> None:
    _CHECKOUTS.pop(_scoped_session_key(session_id, tenant_id), None)


def export_checkout_state(session_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
    """Serialize the current checkout state for persistence."""
    state = get_checkout(session_id, tenant_id)
    if state is None:
        return None
    return asdict(state)


def restore_checkout_state(
    session_id: str,
    data: dict[str, Any] | None,
    tenant_id: str | None = None,
) -> CheckoutState | None:
    """Restore one checkout snapshot loaded from persistence."""
    if not data:
        clear_checkout(session_id, tenant_id)
        return None

    state = CheckoutState(
        session_id=session_id,
        step=data.get("step", "review"),
        profile_id=data.get("profile_id", "default_demo"),
        shipping=data.get("shipping"),
        payment=data.get("payment"),
        totals=dict(data.get("totals", {})),
        cart_snapshot=list(data.get("cart_snapshot", [])),
        order_id=data.get("order_id"),
        last_updated_at=data.get("last_updated_at", datetime.now(UTC).isoformat()),
    )
    _CHECKOUTS[_scoped_session_key(session_id, tenant_id)] = state
    return state
