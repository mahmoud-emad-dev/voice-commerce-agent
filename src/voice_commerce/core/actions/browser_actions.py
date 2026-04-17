from __future__ import annotations
from typing import Literal , Union , Annotated

from pydantic import BaseModel , Field

type NotificationLevel = Literal["success", "error", "info", "warning"]

# ── Base ─────────────────────────────────────────────────────────────────────

class  _ActionBase(BaseModel):
    """Common envelope all actions share."""

    type : Literal["action"] = "action"

    def to_ws_json(self) -> str:
        """Serialize for sending over WebSocket."""
        return self.model_dump_json()


# ── Individual action models ──────────────────────────────────────────────────

## Product actions
class HighlightProduct(_ActionBase):
    """
    Draw a visual ring around a product card on the store page.
    The browser JS looks for  [data-product-id="<product_id>"]  and
    adds a CSS class that pulses with a blue border for 3 seconds.
    """
    action: Literal["highlight_product"] = "highlight_product"
    product_id: int
    scroll_to: bool = True
    
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
    count: int         # total items in cart

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
    duration_ms: int = 3000      # how long before it fades

class SetSearchQuery(_ActionBase):
    """
    Pre-fill the store's search input and optionally submit it.
    Useful when the assistant says 'let me search for leather belts for you'.
    """
    action: Literal["set_search_query"] = "set_search_query"
    query: str
    submit: bool = False         # True = also submit the form

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
        ShowProductModal,
        SetSearchQuery,
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

def highlight(product_id: int, *, scroll: bool = True) -> HighlightProduct:
    return HighlightProduct(product_id=product_id, scroll_to=scroll)
 
def notify(message: str, level: NotificationLevel = "info", duration_ms: int = 3000) -> ShowNotification:
    return ShowNotification(message=message, level=level, duration_ms=duration_ms)  
 
def update_badge(count: int) -> UpdateCartBadge:
    return UpdateCartBadge(count=count)

def add_to_real_cart(product_id: int, quantity: int = 1) -> AddToRealCart:
    return AddToRealCart(product_id=product_id, quantity=quantity)
 
def open_cart() -> OpenCart:
    return OpenCart()

# def close_cart() -> CloseCart:
#     return CloseCart()

# def show_modal(product_id: int, product_name: str) -> ShowProductModal:
#     return ShowProductModal(product_id=product_id, product_name=product_name)

# def set_search(query: str, submit: bool = False) -> SetSearchQuery:
#     return SetSearchQuery(query=query, submit=submit)

# def clear_highlights() -> ClearHighlights:
#     return ClearHighlights()
