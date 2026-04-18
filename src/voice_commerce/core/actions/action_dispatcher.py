from __future__ import annotations
from typing import Any

import structlog

from voice_commerce.models.tool_response import ToolResponse
from voice_commerce.core.actions.browser_actions import (
    BrowserAction,
    HighlightProduct,
    ClearHighlights,
    ShowProductModal,
    SetSearchQuery,
    highlight,
    notify,
    update_badge,
    add_to_real_cart,
    open_cart,

)

log = structlog.get_logger(__name__)


def _toast_line(text: Any, max_chars: int = 72) -> str:
    """Normalize toast copy to a single short line."""
    one_line = " ".join(str(text).split())
    if len(one_line) <= max_chars:
        return one_line
    return one_line[: max_chars - 1] + "…"

class ActionDispatcher:
    """
    Stateless dispatcher — call dispatch() after every tool invocation.
 
    Usage inside voice_websocket_handler.py:
        dispatcher = ActionDispatcher()
        ...
        result = await tool_dispatcher.call(tool_name, tool_args)
        actions = dispatcher.dispatch(tool_name, tool_args, result)
        for action in actions:
            await ws.send_text(action.to_ws_json()) 
    """
    def dispatch(self, tool_name: str , tool_args: dict[str, Any] , tool_response: ToolResponse) -> list[BrowserAction]:
        """
        Return a list of browser actions triggered by this tool result.
        Empty list = no visual update needed.
        """
        # 1. Generic Error Handling (Intercepts any ToolResponse.error())
        if tool_response.status == "error":
            error_msg = tool_response.ai_text
            return [notify(_toast_line(error_msg), "error")]
        
        # 2. Dynamic Routing (e.g., "_on_add_to_cart")
        method_name = f"_on_{tool_name}"
        handler = getattr(self, method_name, None)
        tool_result : dict = tool_response.data

        if handler is None:
            log.debug("action_dispatcher_no_handler", tool=tool_name)
            return []
        
        try:
            # 3. Call the matched handler
            actions = handler(tool_args, tool_result)
            log.info(
                "action_dispatcher_dispatched",
                tool=tool_name,
                actions=[a.action for a in actions],  # type: ignore[attr-defined]
            )
            return actions
        except Exception as e:
            log.error("action_dispatcher_error", tool=tool_name, error=str(e), exc_info=True)
            return []


    # ── Tool handlers (These now receive the nested `ui_data` dictionary) ─────
    def _on_search_products(self, tool_args: dict[str, Any], tool_result: dict[str, Any]) -> list[BrowserAction]:
        """
        After a product search: stagger-highlight up to 4 results.

        Stagger logic:
          - Item 1 (i=0): delay=0ms,    intensity=primary,   scroll=True
          - Item 2 (i=1): delay=350ms,  intensity=secondary, scroll=False
          - Item 3 (i=2): delay=700ms,  intensity=secondary, scroll=False
          - Item 4 (i=3): delay=1050ms, intensity=secondary, scroll=False

        Result: items appear one-by-one like the AI is finding them in order.
        Primary = bright pulse + lift. Secondary = soft lingering glow.
        Both fade completely after 8 seconds so the page is clean for next search.
        """
        products : list[dict[str, Any]] = tool_result.get("products", [])
        if not products:
            return [notify("No products found. Try different keywords.", "info")]

        # Always wipe previous highlights at the start of a new search
        actions: list[BrowserAction] = [ClearHighlights()]

        STAGGER_MS = 1400
        FADE_MS = 12000

        for i, product in enumerate(products[:4]):
            pid : int | None = product.get("id")
            if pid:
                actions.append(
                    highlight(
                        product_id=pid,
                        scroll=True,
                        delay_ms=i * STAGGER_MS,
                        intensity="primary" if i == 0 else "secondary",
                        auto_fade_ms=FADE_MS,
                        show_badge=True,
                    )
                )

        return actions

    def _on_get_product_details(self, tool_args: dict[str, Any], tool_result: dict[str, Any]) -> list[BrowserAction]:
        """
        After fetching details: show the popup modal + highlight.
        """
        product : dict[str, Any] | None = tool_result.get("product")
        if not product:
            return [notify(_toast_line("Product details not found."), "error")]
        
        pid : int | None = product.get("id")
        product_name : str  = product.get("name" , "Product"  )
        if not pid:
            return [notify(_toast_line("Missing product ID."), "error")]

        images = product.get("images", [])
        thumbnail = product.get("thumbnail", "")
        if not thumbnail and images and isinstance(images[0], dict):
            thumbnail = images[0].get("src", "")

        price = product.get("price", "") or product.get("display_price", "")
        short_desc = product.get("short_description", "") or product.get("short_desc", "")

        category = product.get("category", "")
        if not category:
            categories = product.get("categories", [])
            if categories:
                first_cat = categories[0]
                if isinstance(first_cat, dict):
                    category = first_cat.get("name", "")
                else:
                    category = str(first_cat)

        product_data = {
            "thumbnail": thumbnail,
            "price": price,
            "short_desc": short_desc,
            "category": category,
        }

        actions: list[BrowserAction] = [ClearHighlights()]
        actions.append(highlight(product_id=pid, scroll=True))
        actions.append(
            ShowProductModal(
                product_id=pid,
                product_name=product_name,
                product_data=product_data,
                delay_ms=900,
            )
        )
        return actions
    
    
    def _on_add_to_cart(self, tool_args: dict[str, Any], tool_result: dict[str, Any]) -> list[BrowserAction]:
        """
        After adding to cart:
          1. Green success notification
          2. Update the cart badge counter
          3. Open the side cart panel
          4. Highlight the product (if we know the ID)
        """
        product_id : int | None = tool_args.get("product_id")
        product_name : str | None = tool_args.get("product_name" , "Item")
        cart_count : int | None = tool_result.get("cart_count" ,0)
        raw_quantity = tool_args.get("quantity", 1)
        try:
            quantity = max(1, int(raw_quantity))
        except (TypeError, ValueError):
            quantity = 1

        actions: list[BrowserAction] = [
            notify(_toast_line(f"✓ {product_name} added"), "success", 2000),
            update_badge(cart_count if cart_count is not None else 0),
        ]
        if product_id:
            actions.append(add_to_real_cart(product_id=product_id, quantity=quantity))
        if product_id:
            actions.append(highlight(product_id=product_id, scroll=False))
        
        return actions

    
    def _on_remove_from_cart(self, tool_args: dict[str, Any], tool_result: dict[str, Any]) -> list[BrowserAction]:
        """After removing from cart: update badge, info toast."""
        product_name : str | None = tool_args.get("product_name" , "Item")
        cart_count : int | None = tool_result.get("cart_count" ,1)
        
        actions: list[BrowserAction] = [
            update_badge(cart_count if cart_count is not None else 0),
            notify(_toast_line(f"✕ {product_name} removed"), "info", 1500),
        ]

        return actions

    def _on_show_cart(self, tool_args: dict[str, Any], tool_result: dict[str, Any]) -> list[BrowserAction]:
        """When user asks to see cart: sync the badge + open panel."""
        cart_count = tool_result.get("item_count", 0)
        return [
            update_badge(cart_count),
            open_cart(),
        ]   


    # def _on_clear_cart(
    #     self, args: dict, result: dict
    # ) -> list[BrowserAction]:
    #     """After clearing cart: badge → 0 + green notification."""
    #     return [
    #         update_badge(0),
    #         notify("Cart cleared.", "info"),
    #     ]
 
    # def _on_set_search(
    #     self, args: dict, result: dict
    # ) -> list[BrowserAction]:
    #     """Pre-fill the store search input."""
    #     query = args.get("query", "")
    #     submit = args.get("submit", False)
    #     return [SetSearchQuery(query=query, submit=submit)]
 
    # def _on_rag_search(
    #     self, args: dict, result: dict
    # ) -> list[BrowserAction]:
    #     """
    #     After RAG semantic search: highlight top result.
    #     RAG results may come from rag_service.py as a list of product dicts.
    #     """
    #     products = result.get("products", [])
    #     if not products:
    #         return [notify("No matching products found.", "info")]
 
    #     actions: list[BrowserAction] = [ClearHighlights()]
    #     for i, product in enumerate(products[:4]):
    #         pid = product.get("id")
    #         if pid:
    #             actions.append(
    #                 HighlightProduct(product_id=pid, scroll=(i == 0))
    #             )
    #     return actions
    # # ── Fallback: any tool with 'error' key ───────────────────────────────────
    # def _generic_error_check(self, result: dict) -> list[BrowserAction]:
    #     """Utility — call from any handler to surface errors as notifications."""
    #     if err := result.get("error"):
    #         return [notify(str(err), "error")]
    #     return []
