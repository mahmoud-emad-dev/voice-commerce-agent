from __future__ import annotations

from datetime import datetime
import random
import string
from typing import Literal

import structlog

from voice_commerce.core.state.checkout_state import (
    CheckoutState,
    PaymentOption,
    ShippingOption,
    clear_checkout,
    get_checkout,
    set_checkout,
)
from voice_commerce.core.tools import cart_tools
from voice_commerce.models.cart import Cart
from voice_commerce.models.tool_response import ToolResponse

log = structlog.get_logger(__name__)

DEFAULT_PROFILE = {
    "id": "default_demo",
    "first_name": "Omar",
    "last_name": "Al-Qahtani",
    "email": "omar.alqahtani.demo@nexfit.example",
    "phone": "+966 50 638 2147",
    "address_1": "318 King Abdullah Road",
    "city": "Riyadh",
    "state": "Riyadh Province",
    "zip": "12435",
    "country": "Saudi Arabia",
    "payment_labels": {
        "card": "Visa Demo •••• 2147",
        "paypal": "PayPal omar.alqahtani.demo@nexfit.example",
    },
    "masked_card": "•••• •••• •••• 2147",
}

AVAILABLE_SHIPPING_OPTIONS = [
    {"value": "standard", "label": "Standard", "description": "Free over $75, otherwise $9.99"},
    {"value": "express", "label": "Express", "description": "2-day delivery for $14.99"},
]
AVAILABLE_PAYMENT_OPTIONS = [
    {"value": "card", "label": "Card"},
    {"value": "paypal", "label": "PayPal"},
]
VALID_SHIPPING = {option["value"] for option in AVAILABLE_SHIPPING_OPTIONS}
VALID_PAYMENT = {option["value"] for option in AVAILABLE_PAYMENT_OPTIONS}
STANDARD_SHIPPING_FEE = 9.99
EXPRESS_SHIPPING_FEE = 14.99
FREE_SHIPPING_THRESHOLD = 75.0
TAX_RATE = 0.08


def _snapshot_from_cart(cart: Cart) -> list[dict]:
    return [
        {
            "product_id": item.product_id,
            "name": item.name,
            "price": item.price,
            "quantity": item.quantity,
            "subtotal": item.subtotal,
        }
        for item in cart.items.values()
    ]


def _normalize_snapshot_items(items: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for raw in items:
        try:
            product_id = int(raw.get("product_id", raw.get("id", 0)) or 0)
            quantity = max(0, int(raw.get("quantity", raw.get("qty", 0)) or 0))
            price = round(float(raw.get("price", 0) or 0), 2)
        except (TypeError, ValueError):
            continue
        if quantity <= 0:
            continue
        normalized.append({
            "product_id": product_id,
            "quantity": quantity,
            "price": price,
        })
    return sorted(normalized, key=lambda item: (item["product_id"], item["quantity"], item["price"]))


def _shipping_cost(subtotal: float, shipping: ShippingOption | None) -> float:
    if shipping == "express":
        return EXPRESS_SHIPPING_FEE
    if subtotal >= FREE_SHIPPING_THRESHOLD:
        return 0.0
    return STANDARD_SHIPPING_FEE


def _compute_totals(cart_snapshot: list[dict], shipping: ShippingOption | None = None) -> dict[str, float]:
    subtotal = round(sum(float(item.get("subtotal", 0)) for item in cart_snapshot), 2)
    shipping_cost = round(_shipping_cost(subtotal, shipping), 2)
    tax = round(subtotal * TAX_RATE, 2)
    total = round(subtotal + shipping_cost + tax, 2)
    return {
        "subtotal": subtotal,
        "shipping": shipping_cost,
        "tax": tax,
        "total": total,
    }


def _shipping_summary(shipping: ShippingOption | None) -> str:
    if shipping == "express":
        return "Express shipping"
    return "Standard shipping"


def _payment_summary(payment: PaymentOption | None) -> str:
    if payment == "paypal":
        return "PayPal"
    return "Card"


def _generate_order_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"DEMO-{datetime.utcnow():%Y%m%d}-{suffix}"


def _serialize_state(state: CheckoutState, *, demo_notice: str | None = None) -> dict:
    return {
        "checkout": {
            "step": state.step,
            "profile": DEFAULT_PROFILE,
            "profile_id": state.profile_id,
            "shipping": state.shipping,
            "payment": state.payment,
            "available_shipping_options": AVAILABLE_SHIPPING_OPTIONS,
            "available_payment_options": AVAILABLE_PAYMENT_OPTIONS,
            "totals": state.totals,
            "cart_snapshot": state.cart_snapshot,
            "order_id": state.order_id,
            "demo_notice": demo_notice or "Demo checkout only. No real charge will happen.",
            "is_open": state.is_open,
            "last_updated_at": state.last_updated_at,
        }
    }


def invalidate_checkout_if_cart_changed(session_id: str, browser_items: list[dict]) -> bool:
    state = get_checkout(session_id)
    if state is None or not state.is_open:
        return False

    old_snapshot = _normalize_snapshot_items(state.cart_snapshot)
    new_snapshot = _normalize_snapshot_items(browser_items)
    if old_snapshot == new_snapshot:
        return False

    clear_checkout(session_id)
    return True


async def begin_checkout(session_id: str = "default") -> ToolResponse:
    cart = cart_tools.get_cart(session_id)
    if cart.is_empty():
        clear_checkout(session_id)
        return ToolResponse.error("Your cart is empty. Add something first, then I can start checkout.")

    state = CheckoutState(
        session_id=session_id,
        step="review",
        profile_id=DEFAULT_PROFILE["id"],
        cart_snapshot=_snapshot_from_cart(cart),
    )
    state.totals = _compute_totals(state.cart_snapshot)
    set_checkout(state)

    return ToolResponse.success(
        ai_text=(
            f"Your cart has {cart.item_count} item{'s' if cart.item_count != 1 else ''} "
            f"for ${state.totals['total']:.2f}. Which shipping would you like, standard or express?"
        ),
        data={
            **_serialize_state(state),
            "cart_count": cart.item_count,
        },
    )


async def set_checkout_option(
    field: Literal["shipping", "payment"],
    value: str,
    session_id: str = "default",
) -> ToolResponse:
    state = get_checkout(session_id)
    if state is None or not state.is_open:
        return ToolResponse.error("Checkout is not active yet. Say checkout when you're ready.")

    normalized = str(value or "").strip().lower()
    if field == "shipping":
        if normalized not in VALID_SHIPPING:
            return ToolResponse.error("Please choose standard or express shipping.")
        state.shipping = normalized  # type: ignore[assignment]
        state.totals = _compute_totals(state.cart_snapshot, state.shipping)
        state.step = "payment"
        set_checkout(state)
        return ToolResponse.success(
            ai_text=(
                f"{_shipping_summary(state.shipping)} is set. For payment, would you like card or PayPal?"
            ),
            data=_serialize_state(state),
        )

    if normalized not in VALID_PAYMENT:
        return ToolResponse.error("Please choose card or PayPal.")
    if state.shipping is None:
        return ToolResponse.error("Choose shipping first: standard or express.")

    state.payment = normalized  # type: ignore[assignment]
    state.step = "confirm"
    set_checkout(state)
    return ToolResponse.success(
        ai_text=(
            f"Great. Your demo total is ${state.totals['total']:.2f} with {_payment_summary(state.payment)}. "
            "Say \"place order\" to confirm."
        ),
        data=_serialize_state(state),
    )


async def confirm_checkout(session_id: str = "default") -> ToolResponse:
    state = get_checkout(session_id)
    if state is None or not state.is_open:
        return ToolResponse.error("Checkout is not active yet.")
    if state.shipping is None or state.payment is None:
        return ToolResponse.error("I still need both shipping and payment before I can place the demo order.")

    state.order_id = _generate_order_id()
    state.step = "success"
    state.totals = _compute_totals(state.cart_snapshot, state.shipping)
    set_checkout(state)
    cart_tools.clear_cart(session_id)

    return ToolResponse.success(
        ai_text=(
            f"Done. Your demo order {state.order_id} is confirmed for ${state.totals['total']:.2f}."
        ),
        data={
            **_serialize_state(state, demo_notice="Demo order placed. No payment was processed."),
            "cart_count": 0,
        },
    )


async def cancel_checkout(session_id: str = "default") -> ToolResponse:
    state = get_checkout(session_id)
    if state is None:
        return ToolResponse.success(
            ai_text="Checkout is already closed.",
            data={"checkout_closed": True},
        )

    state.step = "cancelled"
    set_checkout(state)
    clear_checkout(session_id)
    return ToolResponse.success(
        ai_text="Checkout closed. Your cart is still there whenever you're ready.",
        data={"checkout_closed": True},
    )
