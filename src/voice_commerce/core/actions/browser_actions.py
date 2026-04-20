from __future__ import annotations
from typing import Literal, Union, Annotated

from pydantic import BaseModel, Field

type NotificationLevel = Literal["success", "error", "info", "warning"]

# ── Base ─────────────────────────────────────────────────────────────────────


class _ActionBase(BaseModel):
    """Common envelope all actions share."""

    type: Literal["action"] = "action"

    def to_ws_json(self) -> str:
        """Serialize for sending over WebSocket."""
        return self.model_dump_json()


# ── Individual action models ──────────────────────────────────────────────────


## Product actions
class HighlightProduct(_ActionBase):
    """
    Draw a visual ring around a product card on the store page.
    delay_ms  : stagger offset so results appear one-by-one
    intensity : 'primary' = bright pulse + lift (first result)
                'secondary' = soft glow (results 2-4, and transcript mentions)
    auto_fade_ms: total ms before highlight fully fades away
    show_badge: whether the browser should render the numeric search-order badge
    """

    action: Literal["highlight_product"] = "highlight_product"
    product_id: int
    scroll_to: bool = True
    delay_ms: int = 0
    intensity: Literal["primary", "secondary"] = "primary"
    auto_fade_ms: int = 8000
    show_badge: bool = False


class ScrollToProduct(_ActionBase):
    """
    Smooth-scroll the store page to a product without highlighting it.
    Useful for 'let me show you the running shoes' without drawing attention.
    """

    action: Literal["scroll_to_product"] = "scroll_to_product"
    product_id: int


## Cart actions
class UpdateCartBadge(_ActionBase):
    """
    Update the floating cart icon badge count.
    Call this immediately after add_to_cart succeeds so the badge
    reflects the new total without a full page reload.
    """

    action: Literal["update_cart_badge"] = "update_cart_badge"
    count: int  # total items in cart


class AddToRealCart(_ActionBase):
    """
    Tell the browser to make the real cart AJAX call.
    For WooCommerce: POST /?wc-ajax=add_to_cart.
    For embed_demo.html: dispatches window event 'vc:addToCart'.
    This is separate from UpdateCartBadge (cosmetic badge count only).
    """

    action: Literal["add_to_real_cart"] = "add_to_real_cart"
    product_id: int
    quantity: int = 1


class OpenCart(_ActionBase):
    """
    Slide open the WooCommerce cart side-panel (or drawer).
    Triggered after the assistant adds something so the user can review.
    """

    action: Literal["open_cart"] = "open_cart"


class CloseCart(_ActionBase):
    """
    Close the WooCommerce cart side-panel (or drawer).
    Triggered after the assistant adds something so the user can review.
    """

    action: Literal["close_cart"] = "close_cart"


class RenderCheckout(_ActionBase):
    """
    Render the full demo checkout state in the browser.
    The frontend treats this as the single source of truth for the checkout UI.
    """

    action: Literal["render_checkout"] = "render_checkout"
    checkout: dict


class CloseCheckout(_ActionBase):
    """Close the active demo checkout UI."""

    action: Literal["close_checkout"] = "close_checkout"


## Other Actions
class ShowProductModal(_ActionBase):
    """
    Open a quick-view modal for a product.
    product_data carries display fields so the modal never scrapes the DOM.
    All display data travels with the action — DOM may not have this product visible.
    """

    action: Literal["show_product_modal"] = "show_product_modal"
    product_id: int
    product_name: str
    delay_ms: int = 0
    product_data: dict | None = None


class ShowNotification(_ActionBase):
    """
    Flash a toast notification at the top-right of the store page.
    type controls colour: 'success' → green, 'error' → red,
                          'info' → blue, 'warning' → amber.
    """

    action: Literal["show_notification"] = "show_notification"
    message: str
    level: NotificationLevel = "info"
    duration_ms: int = 3000  # how long before it fades


class SetSearchQuery(_ActionBase):
    """
    Pre-fill the store's search input and optionally submit it.
    Useful when the assistant says 'let me search for leather belts for you'.
    """

    action: Literal["set_search_query"] = "set_search_query"
    query: str
    submit: bool = False  # True = also submit the form


class ApplyFilter(_ActionBase):
    """
    Apply a visual store filter such as category or price.
    value is the raw filter value; label is human-readable UI copy.
    """

    action: Literal["apply_filter"] = "apply_filter"
    filter_type: Literal["category", "price", "brand", "tag"] = "category"
    value: str
    label: str


class ApplySort(_ActionBase):
    """
    Apply a visual store sort mode such as price ascending or popularity.
    """

    action: Literal["apply_sort"] = "apply_sort"
    sort_by: Literal["price_asc", "price_desc", "name", "popularity", "newest"] = "price_asc"
    label: str


class ClearHighlights(_ActionBase):
    """Remove all active highlights from the page (housekeeping)."""

    action: Literal["clear_highlights"] = "clear_highlights"


# ── Discriminated union ───────────────────────────────────────────────────────


BrowserAction = Annotated[
    Union[
        HighlightProduct,
        ScrollToProduct,
        UpdateCartBadge,
        AddToRealCart,
        ShowNotification,
        OpenCart,
        CloseCart,
        RenderCheckout,
        CloseCheckout,
        ShowProductModal,
        SetSearchQuery,
        ApplyFilter,
        ApplySort,
        ClearHighlights,
    ],
    Field(discriminator="action"),
]
"""
Use  BrowserAction  as the type hint when you accept any action.
Pydantic resolves the right concrete class via the `action` literal field.
 
Example:
    raw = {"type": "action", "action": "highlight_product", "product_id": 3}
    act = TypeAdapter(BrowserAction).validate_python(raw)
    # act is now a HighlightProduct instance
"""


# Convenience helpers used by action_dispatcher --------------------------------


def highlight(
    product_id: int,
    *,
    scroll: bool = True,
    delay_ms: int = 0,
    intensity: Literal["primary", "secondary"] = "primary",
    auto_fade_ms: int = 8000,
    show_badge: bool = False,
) -> HighlightProduct:
    return HighlightProduct(
        product_id=product_id,
        scroll_to=scroll,
        delay_ms=delay_ms,
        intensity=intensity,
        auto_fade_ms=auto_fade_ms,
        show_badge=show_badge,
    )


def notify(
    message: str, level: NotificationLevel = "info", duration_ms: int = 3000
) -> ShowNotification:
    return ShowNotification(message=message, level=level, duration_ms=duration_ms)


def update_badge(count: int) -> UpdateCartBadge:
    return UpdateCartBadge(count=count)


def add_to_real_cart(product_id: int, quantity: int = 1) -> AddToRealCart:
    return AddToRealCart(product_id=product_id, quantity=quantity)


def open_cart() -> OpenCart:
    return OpenCart()


def render_checkout(checkout: dict) -> RenderCheckout:
    return RenderCheckout(checkout=checkout)


def close_checkout() -> CloseCheckout:
    return CloseCheckout()


def apply_filter(
    filter_type: Literal["category", "price", "brand", "tag"],
    value: str,
    label: str,
) -> ApplyFilter:
    return ApplyFilter(filter_type=filter_type, value=value, label=label)


def apply_sort(
    sort_by: Literal["price_asc", "price_desc", "name", "popularity", "newest"],
    label: str,
) -> ApplySort:
    return ApplySort(sort_by=sort_by, label=label)


# def close_cart() -> CloseCart:
#     return CloseCart()

# def show_modal(product_id: int, product_name: str) -> ShowProductModal:
#     return ShowProductModal(product_id=product_id, product_name=product_name)

# def set_search(query: str, submit: bool = False) -> SetSearchQuery:
#     return SetSearchQuery(query=query, submit=submit)

# def clear_highlights() -> ClearHighlights:
#     return ClearHighlights()
