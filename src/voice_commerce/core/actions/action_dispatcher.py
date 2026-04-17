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
    open_cart,

)

log = structlog.get_logger(__name__)

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
            return [notify(error_msg, "error")]
        
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
        After a product search: highlight the top result.
        If no products found, show an info notification.
        """
        products : list[dict[str, Any]] = tool_result.get("products", [])
        if not products:
            return [notify("No products found. Try different keywords.", "info")]
        
        # Always clear previous highlights first
        actions: list[BrowserAction] = [ClearHighlights()]

        # Highlight up to the first 4 products
        for product in products[:4]:
            pid : int | None = product.get("id")
            if pid:
                # Scroll the page only for the very first item
                actions.append(highlight(product_id=pid, scroll=(product==products[0])))

        return actions

    def _on_get_product_details(self, tool_args: dict[str, Any], tool_result: dict[str, Any]) -> list[BrowserAction]:
        """
        After fetching details: show the popup modal + highlight.
        """
        product : dict[str, Any] | None = tool_result.get("product")
        if not product:
            return [notify("No product found.", "error")]
        
        pid : int | None = product.get("id")
        product_name : str  = product.get("name" , "Product"  )
        if not pid:
            return [notify("No product ID found.", "error")]
        
        actions: list[BrowserAction] = [ClearHighlights()]
        actions.append(ShowProductModal(product_id=pid , product_name=product_name))
        actions.append(highlight(product_id=pid, scroll=True))
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
        product_name : str = (
            tool_result.get("product_name")
            or tool_args.get("product_name")
            or "Item"
        )
        cart_count : int | None = tool_result.get("cart_count" ,1)

        actions: list[BrowserAction] = [
            notify(f"✓ {product_name} added to cart", "success"),
            update_badge(cart_count if cart_count is not None else 0),
        ]
        if product_id:
            actions.append(highlight(product_id=product_id, scroll=False))
        
        actions.append(open_cart())
        return actions

    
    def _on_remove_from_cart(self, tool_args: dict[str, Any], tool_result: dict[str, Any]) -> list[BrowserAction]:
        """After removing from cart: update badge, info toast."""
        product_name : str = (
            tool_result.get("product_name")
            or tool_args.get("product_name")
            or "Item"
        )
        cart_count : int | None = tool_result.get("cart_count" ,1)
        
        actions: list[BrowserAction] = [
            update_badge(cart_count if cart_count is not None else 0),
            notify(f"Item {product_name} removed from cart", "info"),
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
