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
from voice_commerce.services.rag_service import get_rag_service
from voice_commerce.models.tool_response import ToolResponse

log = structlog.get_logger(__name__)



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
        products = await rag.search_products(query=query ,limit=5, max_price=max_price ) ## category=category # Uncomment if your rag.search() explicitly takes category!
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

 
