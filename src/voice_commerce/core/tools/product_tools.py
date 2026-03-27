from __future__ import annotations


import structlog





log = structlog.get_logger(__name__)


# ── Fake product data ─────────────────────────────────────────────────────────
# Realistic enough for a shopping demo. Each product has the fields that
# both search_products() and get_product_details() need to return.
# Phase 6: this dict is replaced by WooCommerce REST API responses.
 
_PRODUCTS: list[dict] = [
    {
        "id": 1, "name": "Nike Air Zoom Pegasus 40",
        "price": 129.99, "category": "running shoes",
        "tags": ["running", "lightweight", "road", "daily training"],
        "stock": "in stock", "stock_qty": 24,
        "description": "Lightweight daily running shoe with React foam cushioning.",
        "sku": "NIKE-AZP-40",
    },
    {
        "id": 2, "name": "Adidas Ultraboost 23",
        "price": 189.99, "category": "running shoes",
        "tags": ["running", "boost", "responsive", "long distance"],
        "stock": "in stock", "stock_qty": 12,
        "description": "Energy-returning Boost cushioning built for long runs.",
        "sku": "ADI-UB-23",
    },
    {
        "id": 3, "name": "Hoka Clifton 9",
        "price": 139.99, "category": "running shoes",
        "tags": ["running", "cushioned", "comfortable", "wide toe box"],
        "stock": "in stock", "stock_qty": 8,
        "description": "Maximum cushioning with a smooth, stable ride.",
        "sku": "HOKA-CLF-9",
    },
    {
        "id": 4, "name": "Sony WH-1000XM5",
        "price": 349.99, "category": "headphones",
        "tags": ["noise cancelling", "wireless", "bluetooth", "premium"],
        "stock": "in stock", "stock_qty": 6,
        "description": "Industry-leading noise cancellation, 30-hour battery life.",
        "sku": "SONY-WH-XM5",
    },
    {
        "id": 5, "name": "Apple AirPods Pro (2nd Gen)",
        "price": 249.99, "category": "headphones",
        "tags": ["earbuds", "noise cancelling", "wireless", "apple"],
        "stock": "in stock", "stock_qty": 15,
        "description": "Active noise cancellation with adaptive transparency mode.",
        "sku": "APPLE-APP-2",
    },
    {
        "id": 6, "name": "North Face ThermoBall Jacket",
        "price": 199.99, "category": "jackets",
        "tags": ["warm", "winter", "outdoor", "packable", "insulated"],
        "stock": "low stock", "stock_qty": 3,
        "description": "Warm, packable jacket ideal for cold outdoor adventures.",
        "sku": "TNF-TB-JKT",
    },
    {
        "id": 7, "name": "Levi's 501 Original Jeans",
        "price": 69.99, "category": "clothing",
        "tags": ["jeans", "denim", "casual", "classic"],
        "stock": "in stock", "stock_qty": 30,
        "description": "The original straight-fit jean since 1873.",
        "sku": "LEVI-501-ORG",
    },
    {
        "id": 8, "name": "Champion Reverse Weave Hoodie",
        "price": 59.99, "category": "clothing",
        "tags": ["hoodie", "casual", "warm", "comfortable", "fleece"],
        "stock": "in stock", "stock_qty": 20,
        "description": "Heavyweight shrink-resistant fleece, classic fit.",
        "sku": "CHAMP-RW-HO",
    },
]
 


def _matches(product: dict, query: str) -> bool:
    """Simple keyword matching across name, category, tags, and description."""
    text = (
        product["name"].lower() 
        + " " + product["category"].lower()
        + " " + " ".join(product["tags"]).lower()
        + " " + product["description"].lower()
    )
    # Match if ANY word in the query appears in the searchable text
    words = [word for word in query.lower().split() if len(word) > 2]
    if not words:
        return False

    score = sum(1 for word in words if word in text)
    return score >= max(1, len(words) - 1)


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
    log.info("search_products", query=query, max_price=max_price)

    results =  [product for product in _PRODUCTS if _matches(product, query)]

    if category:
        cat = category.lower().strip()
        results = [product for product in results if cat in product["category"].lower()]

    if max_price is not None:
        results = [ product  for product in results if product["price"] <= max_price]
    
    # Limit to 4 results — voice interface, not a wall of text.
    results = results[:4]

    if not results:
        suffix = f" under ${max_price:.0f}" if max_price else ""
        return (
            f"I didn't find anything matching '{query}'{suffix}. "
            "Try different keywords, or ask me what categories we carry."
        )
    
    count = len(results)
    lines = [f"Found {count} product{'s' if count != 1 else ''} for '{query}':"]
    for p in results:
        lines.append(f"• {p['name']} — ${p['price']:.2f} — {p['stock']} — ID:{p['id']}")
        lines.append(f"  {p['description']}")
    lines.append("\nTo add one to your cart, just say which one.")
    return "\n".join(lines)
    

async def get_product_details(product_id: int, session_id: str = "default") -> str:
    """
    Return full details for a specific product by its ID.
 
    Called when the user asks for more information about something
    they saw in search results: "tell me more about the Nike shoes" →
    Gemini calls this with the product_id from the search results it read.
    """
    log.info("get_product_details", product_id=product_id)

    product = next((p for p in _PRODUCTS if p["id"] == product_id), None)

    if product is None:
        return (
            f"I couldn't find product ID {product_id}. "
            "Try searching again — it may no longer be available."
        )
 
    return (
        f"{product['name']}\n"
        f"Price:       ${product['price']:.2f}\n"
        f"Category:    {product['category'].title()}\n"
        f"Stock:       {product['stock'].title()} ({product['stock_qty']} available)\n"
        f"SKU:         {product['sku']}\n"
        f"Description: {product['description']}\n"
        f"ID:          {product['id']}"
    )


 