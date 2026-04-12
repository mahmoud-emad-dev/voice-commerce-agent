# src/voice_commerce/core/tools/cart_tools.py
# =============================================================================
# PURPOSE:
#   Cart manipulation tools for the Gemini AI.
#
# WHY THIS FILE EXISTS:
#   Allows the AI to add items to the user's cart, view the cart, and remove items.
#   It acts as the bridge between the AI's intent, the Pydantic Cart state, 
#   and the live WooCommerce store inventory.
# =============================================================================


from __future__ import annotations

import structlog

# 1. Import our Live Client and our Pydantic Models!
# from voice_commerce.services.woocommerce_client import get_client
from voice_commerce.services.csv_client import get_client
from voice_commerce.models.tool_response import ToolResponse
from voice_commerce.models.cart import Cart, CartItem

log = structlog.get_logger(__name__)

# Module-level dict — persists for the lifetime of the Python process.
# Survives multiple conversation turns within one session.

_CARTS: dict[str, Cart] = {} 

def _get_cart(session_id: str) -> Cart:
    """Helper to get the cart for a session, creating it if it doesn't exist."""
    if session_id not in _CARTS:
        _CARTS[session_id] = Cart(session_id=session_id)
    return _CARTS[session_id]


# Tools methods

async def add_to_cart( product_id: int,quantity: int = 1, session_id: str = "default") -> ToolResponse:
    """
    Add a product to the customer's cart, validated against live WooCommerce data.
    """

    log.info("add_to_cart_live", product_id=product_id, quantity=quantity, session=session_id)

    if quantity < 1:
        return ToolResponse.error("Please specify a quantity of 1 or more.")
    
    try:
        # 1. Validate against LIVE WooCommerce
        client = get_client()
        product = await client.get_product(product_id)
        # Handle 404 (AI hallucinated the ID or it was deleted)
        if product is None:
            return ToolResponse.error(
                f"I couldn't find product ID {product_id}. "
                "Try searching again — it may no longer be available."
            )
        # Handle Out of Stock
        if not product.is_in_stock:
            return ToolResponse.error(f"Sorry, '{product.name}' is currently out of stock.")

        # # Handle Variations (Simple)
        # if product.has_variations:
        #     return (
        #         f"'{product.name}' has variations (e.g. size, color). "
        #         "Please specify which variation you want to add."
        #     )

        # 2. Add to our Pydantic Cart
        cart = _get_cart(session_id)

        if product_id in cart.items:
            cart.items[product_id].quantity = quantity
            action = "Updated"
        else:
            cart.items[product_id] = CartItem(
                product_id=product.id,
                name=product.name,
                price=product.price,
                quantity=quantity,
            )
            action = "Added"



        # 3. Format the response
        item = cart.items[product_id]
        ai_text=  (
            f"{action} {item.quantity}× {item.name} "
            f"(${item.price:.2f} each) to your cart.\n"
            f"Cart total: ${cart.total:.2f} "
            f"({cart.item_count} item{'s' if cart.item_count != 1 else ''})"
        )
        # 4. Return the explicit data the Action Dispatcher needs for the UI
        return ToolResponse.success(
            ai_text=ai_text ,
            data={
                "product_id": product_id,       # Tells UI which item to highlight
                "product_name": item.name,      # Tells UI what to put in the green toast
                "cart_count": cart.item_count   # Tells UI what number to put on the cart badge
                }
            )
    
    except RuntimeError:
        return ToolResponse.error("My connection to the store's database is currently offline.")
    except Exception as e:
        log.error("tool_add_to_cart_error", error=str(e))
        return ToolResponse.error("I'm having trouble adding that to the cart right now. Please try again.")



    

async def show_cart(session_id: str = "default") -> ToolResponse:
    """Show the customer's current cart contents and total."""
    log.info("show_cart", session=session_id)
    cart = _get_cart(session_id)
    response = cart.to_tool_response()
    return ToolResponse.success(ai_text=response["ai_text"] , data=response["data"])


async def remove_from_cart(product_id: int,session_id: str = "default") -> ToolResponse:
    """Remove a product from the cart by its ID."""
    log.info("remove_from_cart", product_id=product_id, session=session_id)
 
    cart = _get_cart(session_id)
    if product_id not in cart.items:
        return ToolResponse.error(
            error_msg=f"Product ID {product_id} isn't in your cart. "
            "Say 'show my cart' to see what's in it."
        )
 
    name = cart.items[product_id].name
    del cart.items[product_id]
 
    if cart.is_empty():
        return ToolResponse.success(f"Removed {name}. Your cart is now empty.")
    
    # We must pass cart_count so the UI badge updates correctly!
    ai_text = f"Removed {name} from your cart. New total: ${cart.total:.2f}"
    return ToolResponse.success(
        ai_text=ai_text ,
        data={
            "product_id": product_id, 
            "product_name": name,     
            "cart_count": cart.item_count   
            }
        )

    


