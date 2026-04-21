from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


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
    last_updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @property
    def is_open(self) -> bool:
        """True while the checkout can still be updated by the user."""
        return self.step not in {"success", "cancelled"}

    def touch(self) -> None:
        """Refresh the timestamp whenever the checkout state changes."""
        self.last_updated_at = datetime.utcnow().isoformat()


_CHECKOUTS: dict[str, CheckoutState] = {}


def get_checkout(session_id: str) -> CheckoutState | None:
    return _CHECKOUTS.get(session_id)


def set_checkout(state: CheckoutState) -> CheckoutState:
    state.touch()
    _CHECKOUTS[state.session_id] = state
    return state


def clear_checkout(session_id: str) -> None:
    _CHECKOUTS.pop(session_id, None)
