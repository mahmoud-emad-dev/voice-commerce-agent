from typing import Any

from google.genai import types





# -----------------------------------------------------------------------------
# PRODUCT TOOLS
# -----------------------------------------------------------------------------
 
SEARCH_PRODUCTS_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_products",
            description=(
                "Search the store's product catalog using natural language and return actual product matches. "
                "Use this when the customer wants products, options, recommendations, or more items in a product type. "
                "This includes requests like 'show me shorts', 'more shorts', 'summer clothing', "
                "'light jackets', or 'find me something under $50'. "
                "Use this instead of search_categories when the user wants actual products, not just category names. "
                "Do not call this for filler, partial, or ambiguous voice utterances such as "
                "'what about', 'okay', '.', 'yes', or unfinished speech. "
                "If the request is unclear, ask a short clarification question first."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description=(
                            "The natural language search query. Use the user's words "
                            "directly, in their language (Arabic or English both work). "
                            "Include price if mentioned, e.g. 'running shoes under $100'."
                        ),
                    ),
                    "max_price": types.Schema(
                        type=types.Type.NUMBER,
                        description=(
                            "Optional maximum price filter in USD. "
                            "Only include if the user specifically mentioned a price limit."
                        ),
                    ),
                },
                required=["query"],
                # max_price is optional — not in required list
            ),
        )
    ]
)
SEARCH_CATEGORIES_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_categories",
            description=(
                "List all product categories available in the store, or get products "
                "from a specific category. Call this when the user asks to browse "
                "instead of search by keyword. Examples: 'what categories do you have', "
                "'what do you sell', 'show me all running gear', 'browse yoga', "
                "or 'what is in the cycling section'. Returns category names with product "
                "counts when called with no arguments, or products in that category "
                "when given a category name. Do not use this for open-ended product finding "
                "or recommendation requests like 'more shorts' or 'find light summer clothes'; "
                "use search_products for those."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "category": types.Schema(
                        type=types.Type.STRING,
                        description=(
                            "Optional exact category name to browse, such as 'Running' or 'Yoga'. "
                            "Omit to list all categories."
                        ),
                    ),
                    "max_price": types.Schema(
                        type=types.Type.NUMBER,
                        description="Optional price ceiling when listing products from a category.",
                    ),
                    "in_stock_only": types.Schema(
                        type=types.Type.BOOLEAN,
                        description="If true, only return products that are currently in stock.",
                    ),
                },
            ),
        )
    ]
)


GET_PRODUCT_DETAILS_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="get_product_details",
            description=(
                "Get detailed information about a specific product by its ID. "
                "Call this when the user asks for more details about a product "
                "that was already shown in search results, or when you have a "
                "product ID and need full details like description, stock status, "
                "images, or specifications."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "product_id": types.Schema(
                        type=types.Type.INTEGER,
                        description="The numeric product ID from search results.",
                    ),
                },
                required=["product_id"],
            ),
          )
    ]
)


# -----------------------------------------------------------------------------
# CART TOOLS
# -----------------------------------------------------------------------------


ADD_TO_CART_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="add_to_cart",
            description=(
                "Add a product to the customer's shopping cart. "
                "Only call this after the customer clearly confirms they want this specific product. "
                "product_id MUST be the exact integer ID returned by search_products or get_product_details. "
                "Never guess, invent, or derive a product_id from the product name. "
                "If you do not have a confirmed integer product_id, call search_products first. "
                "Example: user says 'add the first one' after search returned id=47 -> "
                "call add_to_cart(product_id=47, quantity=1)."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "product_id": types.Schema(
                        type=types.Type.INTEGER,
                        description=(
                            "The integer product ID returned by search_products. "
                            "Must be a number (e.g., 42), not a product name string."
                        ),
                    ),
                    "quantity": types.Schema(
                        type=types.Type.INTEGER,
                        description=(
                            "Number of items to add. Defaults to 1 if not specified."
                        ),
                    ),
                },
                required=["product_id"],
            ),
        )
    ]
)


SHOW_CART_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="show_cart",
            description=(
                "Show the customer's current shopping cart contents. "
                "Call this when the user asks to see their cart, asks what's "
                "in their cart, or asks about their total. "
                "Returns all items in cart with quantities and total price."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={},
                # No parameters needed — cart is identified by session
            ),
        )
    ]
)

REMOVE_FROM_CART_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="remove_from_cart",
            description=(
                "Remove a product from the customer's shopping cart. "
                "Confirm before removing, e.g. 'Should I remove the Nike shoes from your cart?' "
                "Returns updated cart contents after removal."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "product_id": types.Schema(
                        type=types.Type.INTEGER,
                        description="The numeric ID of the product to remove.",
                    ),
                },
                required=["product_id"],
            ),
        )
    ]
)


# =============================================================================
# REGISTRY — the list exported to gemini_live_handler.py
# =============================================================================
 
# All tools available to Gemini in the current phase.
# Phase 3: fake data implementations
# Phase 6: real WooCommerce REST API implementations
# Phase 7: RAG-powered search implementation


ALL_TOOLS: list[types.Tool] = [
    SEARCH_PRODUCTS_TOOL,
    SEARCH_CATEGORIES_TOOL,
    GET_PRODUCT_DETAILS_TOOL,
    ADD_TO_CART_TOOL,
    SHOW_CART_TOOL,
    REMOVE_FROM_CART_TOOL,
]


def get_all_tools() -> list[types.Tool]:
    """
    Return all tool declarations for use in Gemini session config.
 
    Called by gemini_live_handler.py when building the session config:
        tools=tool_registry.get_all_tools()
 
    Returns:
        List of types.Tool objects to pass to LiveConnectConfig(tools=...)
    """
    return ALL_TOOLS


# Map of tool name → the Tool object containing it.
# Used for validation: check a tool call name is registered before dispatching.
# Map of tool name → the Tool object containing it.
# Used for validation: check a tool call name is registered before dispatching.
TOOL_NAME_MAP: dict[str, types.Tool] = {
    fd.name: tool
    for tool in ALL_TOOLS
    for fd in (tool.function_declarations or [])  # <--- THE FIX: Add 'or []'
    if fd.name is not None
} 
 
def is_registered(tool_name: str) -> bool:
    """
    Check whether a tool name is in the registry.
 
    Used by the dispatcher to catch Gemini hallucinating tool names
    (rare, but possible — Gemini may sometimes invent tool names that
    don't exist if the session config wasn't sent correctly).
    """
    return tool_name in TOOL_NAME_MAP
 
 
def get_registered_names() -> list[str]:
    """Return all registered tool names. Useful for logging and debugging."""
    return list(TOOL_NAME_MAP.keys())
