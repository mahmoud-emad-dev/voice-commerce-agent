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
    apply_filter,
    apply_sort,
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


def _infer_sort_action(tool_name: str, tool_args: dict[str, Any]) -> BrowserAction | None:
    """Infer a browser-side sort action from search phrasing when intent is obvious."""
    if tool_name not in {"search_products", "search_categories"}:
        return None

    query_parts = []
    if tool_args.get("query"):
        query_parts.append(str(tool_args.get("query")))
    if tool_args.get("category"):
        query_parts.append(str(tool_args.get("category")))
    normalized = " ".join(query_parts).strip().lower()
    if not normalized:
        return None

    if any(
        token in normalized
        for token in ("cheapest", "lowest price", "low price", "price low", "under $", "budget")
    ):
        return apply_sort("price_asc", "Sorted: Lowest price")
    if any(
        token in normalized
        for token in ("most expensive", "highest price", "premium", "luxury", "price high")
    ):
        return apply_sort("price_desc", "Sorted: Highest price")
    if any(token in normalized for token in ("alphabetical", "a to z", "by name", "name order")):
        return apply_sort("name", "Sorted: Name")
    if any(
        token in normalized
        for token in ("popular", "popularity", "best selling", "best-selling", "top selling")
    ):
        return apply_sort("popularity", "Sorted: Popularity")
    return None


def _infer_filter_actions(
    tool_name: str, tool_args: dict[str, Any], tool_result: dict[str, Any]
) -> list[BrowserAction]:
    """Infer browser-side filters from explicit search intent or category browse results."""
    actions: list[BrowserAction] = []

    if tool_name == "search_categories":
        category = tool_result.get("category")
        if category:
            actions.append(
                apply_filter(
                    filter_type="category",
                    value=str(category),
                    label=f"Filtered: {category}",
                )
            )
        return actions

    if tool_name != "search_products":
        return actions

    query = str(tool_args.get("query") or "").strip().lower()
    category_tokens = {
        "short": "Shorts",
        "shorts": "Shorts",
        "jacket": "Jackets",
        "jackets": "Jackets",
        "hoodie": "Hoodies & Sweatshirts",
        "hoodies": "Hoodies & Sweatshirts",
        "sweatshirt": "Hoodies & Sweatshirts",
        "sweatshirts": "Hoodies & Sweatshirts",
        "pant": "Pants",
        "pants": "Pants",
        "tee": "Tees",
        "tees": "Tees",
        "tank": "Tanks",
        "tanks": "Tanks",
        "watch": "Watches",
        "watches": "Watches",
        "bag": "Bags",
        "bags": "Bags",
    }
    for token, category_name in category_tokens.items():
        if token in query:
            actions.append(
                apply_filter(
                    filter_type="category",
                    value=category_name,
                    label=f"Filtered: {category_name}",
                )
            )
            break

    max_price = tool_args.get("max_price")
    if max_price is not None:
        try:
            ceiling = max(0, int(float(max_price)))
        except (TypeError, ValueError):
            ceiling = 0
        if ceiling > 0:
            actions.append(
                apply_filter(
                    filter_type="price",
                    value=f"0-{ceiling}",
                    label=f"Filtered: Under ${ceiling}",
                )
            )

    return actions


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

    def dispatch(
        self, tool_name: str, tool_args: dict[str, Any], tool_response: ToolResponse
    ) -> list[BrowserAction]:
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
        tool_result: dict = tool_response.data

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
    def _on_search_products(
        self, tool_args: dict[str, Any], tool_result: dict[str, Any]
    ) -> list[BrowserAction]:
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
        products: list[dict[str, Any]] = tool_result.get("products", [])
        if not products:
            return [notify("No products found. Try different keywords.", "info")]

        # Always wipe previous highlights at the start of a new search
        actions: list[BrowserAction] = [ClearHighlights()]
        actions.extend(_infer_filter_actions("search_products", tool_args, tool_result))
        sort_action = _infer_sort_action("search_products", tool_args)
        if sort_action is not None:
            actions.append(sort_action)

        # Give the page a moment to apply filter/sort before highlights begin.
        # First highlight after ~1.5s - sync with when Gemini starts talking about first product
        # Stagger by ~2s between products - gives time for "first...", "this one...", etc.
        base_delay_ms = 1500 if len(actions) > 1 else 800
        STAGGER_MS = 2000
        FADE_MS = 10000

        for i, product in enumerate(products[:4]):
            pid: int | None = product.get("id")
            if pid:
                actions.append(
                    highlight(
                        product_id=pid,
                        scroll=True,
                        delay_ms=base_delay_ms + (i * STAGGER_MS),
                        intensity="primary" if i == 0 else "secondary",
                        auto_fade_ms=FADE_MS,
                        show_badge=True,
                    )
                )

        return actions

    def _on_search_categories(
        self, tool_args: dict[str, Any], tool_result: dict[str, Any]
    ) -> list[BrowserAction]:
        """Apply only the native category filter for category browsing."""
        actions: list[BrowserAction] = [ClearHighlights()]
        actions.extend(_infer_filter_actions("search_categories", tool_args, tool_result))

        sort_action = _infer_sort_action("search_categories", tool_args)
        if sort_action is not None:
            actions.append(sort_action)

        return actions

    def _on_get_product_details(
        self, tool_args: dict[str, Any], tool_result: dict[str, Any]
    ) -> list[BrowserAction]:
        """
        After fetching details: show the popup modal + highlight.
        """
        product: dict[str, Any] | None = tool_result.get("product")
        if not product:
            return [notify(_toast_line("Product details not found."), "error")]

        pid: int | None = product.get("id")
        product_name: str = product.get("name", "Product")
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

    def _on_add_to_cart(
        self, tool_args: dict[str, Any], tool_result: dict[str, Any]
    ) -> list[BrowserAction]:
        """
        After adding to cart:
          1. Green success notification
          2. Update the cart badge counter
          3. Open the side cart panel
          4. Highlight the product (if we know the ID)
        """
        product_id: int | None = tool_args.get("product_id")
        product_name: str | None = tool_args.get("product_name", "Item")
        cart_count: int | None = tool_result.get("cart_count", 0)
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

    def _on_remove_from_cart(
        self, tool_args: dict[str, Any], tool_result: dict[str, Any]
    ) -> list[BrowserAction]:
        """After removing from cart: update badge, info toast."""
        product_name: str | None = tool_args.get("product_name", "Item")
        cart_count: int | None = tool_result.get("cart_count", 1)

        actions: list[BrowserAction] = [
            update_badge(cart_count if cart_count is not None else 0),
            notify(_toast_line(f"✕ {product_name} removed"), "info", 1500),
        ]

        return actions

    def _on_show_cart(
        self, tool_args: dict[str, Any], tool_result: dict[str, Any]
    ) -> list[BrowserAction]:
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
