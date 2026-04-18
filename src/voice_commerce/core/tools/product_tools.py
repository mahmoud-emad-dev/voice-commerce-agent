# src/voice_commerce/core/tools/product_tools.py
# =============================================================================
# PURPOSE:
#   Exposes product search and retrieval functions to the Gemini AI.
#
# WHY THIS FILE EXISTS:
#   The AI cannot browse the internet or click through your store. We must give 
#   it strictly defined "Tools" (Python functions) it can call to look up data.
#
# THIS FILE IN THE ARCHITECTURE:
#   - search_products: Now uses the Semantic RAG Engine (Understands meaning/concepts).
#   - get_product_details: Still uses live WooCommerce API for real-time stock/price.
#   These functions are registered in `tool_registry.py` and executed by 
#   `tool_dispatcher.py`. They act as the bridge between the AI's intent 
#   and our `WooCommerceClient`.
# =============================================================================

from __future__ import annotations
from typing import Any

import structlog
# 1. We keep WooCommerce client for getting live details
# from voice_commerce.services.woocommerce_client import get_client
from voice_commerce.services.csv_client import get_client
# 2. We import our new Brain for searching
from voice_commerce.services.rag_service import CategoryProductSnapshot, CategorySummaryEntry, get_rag_service
from voice_commerce.models.tool_response import ToolResponse

log = structlog.get_logger(__name__)


def _format_category_result(category_name: str, summary: CategorySummaryEntry) -> str:
    """Build a concise spoken summary for one category."""
    count = int(summary.get("count", 0))
    sample_names = list(summary.get("example_names", []))[:2]
    sample_text = f" Examples include {', '.join(sample_names)}." if sample_names else ""
    return f"{category_name}: {count} product{'s' if count != 1 else ''}.{sample_text}"
# ── Tool implementations ──────────────────────────────────────────────────────

async def search_products(query: str, max_price: float | None = None, category: str | None = None , session_id: str = "default",) -> ToolResponse:
    """
    Search the product catalog for items matching a natural language query.
 
    Called by the dispatcher when Gemini yields a tool_call with name="search_products".
    Returns a ToolResponse with a list of products for the UI, and a summary for Gemini.
 
    Args:
        query:      What the user is looking for — extracted by Gemini from speech.
        max_price:  Price ceiling in USD — extracted by Gemini if user said e.g. "under $150".
        session_id: Injected by dispatcher. Not needed for search, but accepted
                    so the function signature is consistent with cart tools.
    """
    log.info("search_products_live_rag", query=query, max_price=max_price)

    try:
        rag = get_rag_service()
        # Safety Check: If the server just booted and the background task is still downloading
        if not rag.is_ready:
            log.warning("search_attempted_while_rag_syncing")
            return ToolResponse.error("I am currently updating my catalog database. Please give me a few seconds and try your search again.")
        # 1. Fetch semantic matches from the RAG Brain!
        products = await rag.search_products(query=query, limit=5, max_price=max_price, category=category)
        if not products:
            suffix = f" under ${max_price:.0f}" if max_price else ""
            cat_suffix = f" in {category}" if category else ""
            return ToolResponse.error(f"I didn't find anything matching '{query}'{suffix}{cat_suffix}. Try different keywords or ask me what categories we carry.")

        # 2. Gather the UI data dictionaries (using our new method on the Product model!)  
        count = len(products)
        begining_text = f"Found {count} product{'s' if count != 1 else ''} for '{query}':"
        lines = [begining_text]
        ui_products = []
        # 3. Process both the AI text and UI data in a single pass
        for p in products:
            response_dict = p.to_tool_response(detailed=False)
            lines.append(response_dict["ai_text"])
            ui_products.append(response_dict["data"])

        lines.append("\nTo add one to your cart, just say which one.")
        ai_text = "\n".join(lines)
        # 4. Return the explicit ToolResponse
        return ToolResponse.success(
            ai_text=ai_text,
            data={"products": ui_products}
        )
    except RuntimeError:
        # Caught if settings are missing and WooCommerce never initialized
        return ToolResponse.error("My connection to the store's database is currently offline.")
    except Exception as e:
        log.error("search_products_error", error=str(e))
        return ToolResponse.error("I'm having trouble accessing the semantic catalog right now. Please try again later.")

    

async def get_product_details(product_id: int, session_id: str = "default") -> ToolResponse:
    """
    Return full details for a specific product by its ID.
 
    Called when the user asks for more information about something
    they saw in search results: "tell me more about the Nike shoes" →
    Gemini calls this with the product_id from the search results it read.
    """
    log.info("get_product_details", product_id=product_id)

    try:
        client = get_client()
        # 1. Fetch live Pydantic Product objects
        product = await client.get_product(product_id=product_id) # Live internet search!
        if not product:
            return ToolResponse.error(
                f"I couldn't find product ID {product_id}. "
                "Try searching again — it may no longer be available."
            )
        # 4. Return the deep-dive formatting built directly into our Pydantic model!
        response = product.to_tool_response(detailed=True)
        product_data = response["data"]
        product_data.update(
            {
                "price": product.display_price,
                "short_description": product.short_description,
                "thumbnail": product.images[0].get("src", "") if product.images else "",
                "categories": [{"name": c.name} for c in product.categories],
            }
        )
        return ToolResponse.success(ai_text=response["ai_text"], data={"product": product_data})

    except RuntimeError:
        # Caught if settings are missing and WooCommerce never initialized
        return ToolResponse.error("My connection to the store's database is currently offline.")
    except Exception as e:
        log.error("get_product_details_error", error=str(e))
        return ToolResponse.error("I'm having trouble fetching those details right now. Please try again.")


async def search_categories(
    category: str | None = None,
    max_price: float | None = None,
    in_stock_only: bool = False,
    session_id: str = "default",
) -> ToolResponse:
    """
    Browse catalog by category.

    Mode 1: no category -> list available categories with counts.
    Mode 2: category set -> return products inside that category deterministically.
    """
    log.info("search_categories", category=category, max_price=max_price, in_stock_only=in_stock_only)

    try:
        rag = get_rag_service()
        if not rag.is_ready:
            log.warning("search_categories_attempted_while_rag_syncing")
            return ToolResponse.error("I am still loading the catalog. Please give me a few seconds and ask again.")

        category_summary = rag.category_summary
        if not category_summary:
            return ToolResponse.error("I don't have any category information loaded right now.")

        if not category:
            sorted_categories = rag.search_category_summaries()
            preview_limit = 12
            preview_items = sorted_categories[:preview_limit]
            lines = ["Categories available:"]
            lines.extend(_format_category_result(category_name, summary) for category_name, summary in preview_items)
            if len(sorted_categories) > preview_limit:
                lines.append(
                    f"There are {len(sorted_categories) - preview_limit} more categories available if you want me to browse one."
                )

            return ToolResponse.success(
                ai_text="\n".join(lines),
                data={
                    "categories": [
                        {
                            "name": category_name,
                            "count": int(summary.get("count", 0)),
                            "example_names": list(summary.get("example_names", [])),
                            "subcategories": list(summary.get("subcategories", [])),
                            "parent_groups": list(summary.get("parent_groups", [])),
                        }
                        for category_name, summary in sorted_categories
                    ]
                },
            )

        resolved_category = rag.resolve_category_name(category)
        if not resolved_category:
            return ToolResponse.error(
                f"I couldn't find a category called '{category}'. Ask me what categories we carry for the full list."
            )

        items: list[CategoryProductSnapshot] = rag.get_products_for_category(
            resolved_category,
            max_price=max_price,
            in_stock_only=in_stock_only,
        )
        if not items:
            filter_parts = []
            if max_price is not None:
                filter_parts.append(f"under ${max_price:.0f}")
            if in_stock_only:
                filter_parts.append("currently in stock")
            filter_suffix = f" with filters ({', '.join(filter_parts)})" if filter_parts else ""
            return ToolResponse.success(
                ai_text=f"No products found in {resolved_category}{filter_suffix}.",
                data={"category": resolved_category, "products": []},
            )

        preview = "; ".join(f"{item['name']} ${item['price']:.2f}" for item in items[:5])
        lines = [f"Found {len(items)} products in {resolved_category}."]
        if max_price is not None:
            lines.append(f"Price ceiling applied: ${max_price:.2f}.")
        if in_stock_only:
            lines.append("Only in-stock products are included.")
        lines.append(f"Top matches: {preview}.")
        lines.append("Tell me the product name if you want more details.")

        return ToolResponse.success(
            ai_text=" ".join(lines),
            data={"category": resolved_category, "products": items},
        )
    except Exception as e:
        log.error("search_categories_error", error=str(e))
        return ToolResponse.error("I'm having trouble reading the category list right now. Please try again.")

 
