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
import hashlib
from typing import Any, TypedDict

import structlog
# 1. We keep WooCommerce client for getting live details
# from voice_commerce.services.woocommerce_client import get_client
from voice_commerce.services.csv_client import get_client
# 2. We import our new Brain for searching
from voice_commerce.services.rag_service import CategoryProductSnapshot, CategorySummaryEntry, get_rag_service
from voice_commerce.models.tool_response import ToolResponse

log = structlog.get_logger(__name__)

_DEFAULT_PAGE_SIZE = 5
_MAX_PAGE_SIZE = 10
_MAX_QUERIES_PER_SESSION = 20


class _SearchQueryCacheEntry(TypedDict):
    returned_ids: set[int]
    next_offset: int


_SEARCH_RESULT_CACHE: dict[str, dict[str, _SearchQueryCacheEntry]] = {}


def _query_cache_key(query: str, max_price: float | None, category: str | None) -> str:
    canonical = (
        f"{query.strip().lower()}|"
        f"{'' if max_price is None else f'{max_price:.2f}'}|"
        f"{(category or '').strip().lower()}"
    )
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _ensure_session_cache(session_id: str) -> dict[str, _SearchQueryCacheEntry]:
    cache = _SEARCH_RESULT_CACHE.setdefault(session_id, {})
    if len(cache) >= _MAX_QUERIES_PER_SESSION:
        oldest_key = next(iter(cache))
        cache.pop(oldest_key, None)
    return cache


def _format_category_result(category_name: str, summary: CategorySummaryEntry) -> str:
    """Build a concise spoken summary for one category."""
    count = int(summary.get("count", 0))
    sample_names = list(summary.get("example_names", []))[:2]
    sample_text = f" Examples include {', '.join(sample_names)}." if sample_names else ""
    return f"{category_name}: {count} product{'s' if count != 1 else ''}.{sample_text}"
# ── Tool implementations ──────────────────────────────────────────────────────

async def search_products(
    query: str,
    category: str | None = None,
    max_price: float | None = None,
    limit: int = _DEFAULT_PAGE_SIZE,
    offset: int = 0,
    session_id: str = "default",
) -> ToolResponse:
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
    requested_limit = max(1, min(int(limit), _MAX_PAGE_SIZE))
    requested_offset = max(0, int(offset))
    log.info(
        "search_products_live_rag",
        query=query,
        category=category,
        max_price=max_price,
        limit=requested_limit,
        offset=requested_offset,
        session_id=session_id,
    )

    try:
        rag = get_rag_service()
        # Safety Check: If the server just booted and the background task is still downloading
        if not rag.is_ready:
            log.warning("search_attempted_while_rag_syncing")
            return ToolResponse.error("I am currently updating my catalog database. Please give me a few seconds and try your search again.")
        # 1. Resolve cursor state for this session/query.
        session_cache = _ensure_session_cache(session_id)
        resolved_category = rag.resolve_category_name(category) if category else None
        cache_key = _query_cache_key(query, max_price, resolved_category)
        cache_entry = session_cache.get(cache_key)
        seen_ids = set(cache_entry["returned_ids"]) if cache_entry else set()
        effective_offset = requested_offset or (cache_entry["next_offset"] if cache_entry else 0)

        # 2. Fetch semantic matches with pagination and de-duplication.
        products = []
        attempts = 0
        rolling_offset = effective_offset
        while len(products) < requested_limit and attempts < 3:
            fetch_size = max(requested_limit * 2, requested_limit)
            batch = await rag.search_products(
                query=query,
                limit=fetch_size,
                offset=rolling_offset,
                max_price=max_price,
                category=resolved_category,
            )
            if not batch:
                break

            fresh = [item for item in batch if item.id not in seen_ids]
            if fresh:
                products.extend(fresh)
                products = products[:requested_limit]

            rolling_offset += len(batch)
            attempts += 1
            if len(batch) < fetch_size:
                break

        if not products:
            if effective_offset > 0:
                return ToolResponse.error(
                    f"I couldn't find more results for '{query}'. "
                    "Try a different keyword or adjust the price range."
                )
            suffix = f" under ${max_price:.0f}" if max_price else ""
            category_text = f" in {resolved_category}" if resolved_category else ""
            return ToolResponse.error(
                f"I didn't find anything matching '{query}'{category_text}{suffix}. "
                "Try different keywords or ask me what categories we carry."
            )

        seen_ids.update(p.id for p in products)
        session_cache[cache_key] = {
            "returned_ids": seen_ids,
            "next_offset": rolling_offset,
        }

        # 3. Gather the UI data dictionaries (using our new method on the Product model!)
        count = len(products)
        range_start = effective_offset + 1
        range_end = effective_offset + count
        begining_text = (
            f"Found {count} product{'s' if count != 1 else ''} for '{query}' "
            f"(showing {range_start}-{range_end}):"
        )
        lines = [begining_text]
        ui_products = []
        # 4. Process both the AI text and UI data in a single pass
        for p in products:
            response_dict = p.to_tool_response(detailed=False)
            lines.append(response_dict["ai_text"])
            ui_products.append(response_dict["data"])

        lines.append("\nTo add one to your cart, just say which one.")
        ai_text = "\n".join(lines)
        # 5. Return the explicit ToolResponse with pagination metadata.
        return ToolResponse.success(
            ai_text=ai_text,
            data={
                "products": ui_products,
                "pagination": {
                    "query": query,
                    "limit": requested_limit,
                    "offset": effective_offset,
                    "next_offset": rolling_offset,
                },
            },
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
    limit: int | None = None,
    offset: int = 0,
    session_id: str = "default",
) -> ToolResponse:
    """
    Browse catalog by category.

    Mode 1: no category -> list available categories with counts.
    Mode 2: category set -> return products inside that category deterministically.
    """
    safe_offset = max(0, int(offset))
    safe_limit = max(1, min(int(limit), 25)) if limit is not None else None
    log.info(
        "search_categories",
        category=category,
        max_price=max_price,
        in_stock_only=in_stock_only,
        limit=safe_limit,
        offset=safe_offset,
    )

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
            effective_limit = safe_limit or 12
            preview_items = sorted_categories[safe_offset : safe_offset + effective_limit]
            lines = ["Categories available:"]
            lines.extend(_format_category_result(category_name, summary) for category_name, summary in preview_items)
            shown_total = safe_offset + len(preview_items)
            if len(sorted_categories) > shown_total:
                lines.append(
                    f"There are {len(sorted_categories) - shown_total} more categories available."
                )
            next_offset = safe_offset + len(preview_items)

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
                        for category_name, summary in preview_items
                    ],
                    "pagination": {
                        "offset": safe_offset,
                        "limit": effective_limit,
                        "next_offset": next_offset,
                        "has_more": next_offset < len(sorted_categories),
                    },
                },
            )

        resolved_category = rag.resolve_category_name(category)
        if not resolved_category:
            return ToolResponse.error(
                f"I couldn't find a category called '{category}'. Ask me what categories we carry for the full list."
            )

        total_items: list[CategoryProductSnapshot] = rag.get_products_for_category(
            resolved_category,
            max_price=max_price,
            in_stock_only=in_stock_only,
        )
        effective_limit = safe_limit or 5
        items: list[CategoryProductSnapshot] = rag.get_products_for_category(
            resolved_category,
            max_price=max_price,
            in_stock_only=in_stock_only,
            limit=effective_limit,
            offset=safe_offset,
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
                data={
                    "category": resolved_category,
                    "products": [],
                    "pagination": {
                        "offset": safe_offset,
                        "limit": effective_limit,
                        "next_offset": safe_offset,
                        "has_more": False,
                    },
                },
            )

        preview = "; ".join(f"{item['name']} ${item['price']:.2f}" for item in items[:5])
        range_start = safe_offset + 1
        range_end = safe_offset + len(items)
        lines = [f"Found {len(total_items)} products in {resolved_category} (showing {range_start}-{range_end})."]
        if max_price is not None:
            lines.append(f"Price ceiling applied: ${max_price:.2f}.")
        if in_stock_only:
            lines.append("Only in-stock products are included.")
        lines.append(f"Top matches: {preview}.")
        lines.append("Tell me the product name if you want more details.")
        next_offset = safe_offset + len(items)

        return ToolResponse.success(
            ai_text=" ".join(lines),
            data={
                "category": resolved_category,
                "products": items,
                "pagination": {
                    "offset": safe_offset,
                    "limit": effective_limit,
                    "next_offset": next_offset,
                    "has_more": next_offset < len(total_items),
                },
            },
        )
    except Exception as e:
        log.error("search_categories_error", error=str(e))
        return ToolResponse.error("I'm having trouble reading the category list right now. Please try again.")

 
