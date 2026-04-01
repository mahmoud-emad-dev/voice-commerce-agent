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
from voice_commerce.services import woocommerce_client
# 2. We import our new Brain for searching
from voice_commerce.services.rag_service import get_rag_service

log = structlog.get_logger(__name__)



# ── Tool implementations ──────────────────────────────────────────────────────

async def search_products(query: str, max_price: float | None = None, category: str | None = None , session_id: str = "default",) -> str:
    """
    Search the product catalog for items matching a natural language query.
 
    Called by the dispatcher when Gemini yields a tool_call with name="search_products".
    Returns a formatted string Gemini reads aloud and converts to natural speech.
 
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
            return "I am currently updating my catalog database. Please give me a few seconds and try your search again."
        # 1. Fetch semantic matches from the RAG Brain!
        products = await rag.search_products(query=query ,limit=5, max_price=max_price ) ## category=category # Uncomment if your rag.search() explicitly takes category!
        if not products:
            suffix = f" under ${max_price:.0f}" if max_price else ""
            cat_suffix = f" in {category}" if category else ""
            return f"I didn't find anything matching '{query}'{suffix}{cat_suffix}. Try different keywords or ask me what categories we carry."

        # 2. Format the Pydantic tool summaries perfectly for the AI to read aloud
        count = len(products)
        # 3. Build the response string
        begining_text = f"Found {count} product{'s' if count != 1 else ''} for '{query}':"
        lines = [begining_text]
        for p in products:
            lines.append(p)
        ending_text = "\nTo add one to your cart, just say which one."
        lines.append(ending_text)
        return "\n".join(lines)
    except RuntimeError:
        # Caught if settings are missing and WooCommerce never initialized
        return "My connection to the store's database is currently offline."
    except Exception as e:
        log.error("search_products_error", error=str(e))
        return "I'm having trouble accessing the semantic catalog right now. Please try again later."

    

async def get_product_details(product_id: int, session_id: str = "default") -> str:
    """
    Return full details for a specific product by its ID.
 
    Called when the user asks for more information about something
    they saw in search results: "tell me more about the Nike shoes" →
    Gemini calls this with the product_id from the search results it read.
    """
    log.info("get_product_details", product_id=product_id)

    try:
        client = woocommerce_client.get_client()
        # 1. Fetch live Pydantic Product objects
        product = await client.get_product(product_id=product_id) # Live internet search!
        if not product:
            return (
                f"I couldn't find product ID {product_id}. "
                "Try searching again — it may no longer be available."
            )
        # 4. Return the deep-dive formatting built directly into our Pydantic model!
        return product.to_tool_detail()

    except RuntimeError:
        # Caught if settings are missing and WooCommerce never initialized
        return "My connection to the store's database is currently offline."
    except Exception as e:
        log.error("get_product_details_error", error=str(e))
        return "I'm having trouble fetching those details right now. Please try again."

 