from __future__ import annotations

import structlog

from voice_commerce.core.tools import product_tools

log = structlog.get_logger(__name__)

# Module-level dict — persists for the lifetime of the Python process.
# Survives multiple conversation turns within one session.

_CARTS: dict[str, dict[int, dict]] = {}
 

def _get_cart(session_id: str) -> dict[int, dict]:
    """Helper to get the cart for a session, creating it if it doesn't exist."""
    if session_id not in _CARTS:
        _CARTS[session_id] = {}
    return _CARTS[session_id]


def _cart_total(cart: dict[int, dict]) -> float:
     return round(sum(item["price"] * item["quantity"] for item in cart.values()), 2)


def _item_count(cart: dict[int, dict]) -> int:
    return sum(item["quantity"] for item in cart.values())


async def add_to_cart( product_id: int,quantity: int = 1, session_id: str = "default") -> str:
    """
    Add a product to the customer's cart, validated against known products.
 
    WHY VALIDATE AGAINST THE PRODUCT LIST:
      Gemini extracts product_id from the search results text it previously read.
      Occasionally it hallucinates an ID. Validating before adding protects
      the cart from "Added 5x [nonexistent product]" states.
 
    Phase 6: validation becomes a WooCommerce GET /products/{id} call —
    also checks real-time stock levels and current prices.
    """

    log.info("add_to_cart", product_id=product_id, quantity=quantity, session=session_id)

    if quantity < 1:
        return "Please specify a quantity of 1 or more."
    
    product = next((p for p in product_tools._PRODUCTS if p["id"] == product_id), None)

    if product is None:
        return (
            f"I couldn't find product ID {product_id}. "
            "Try searching again — it may no longer be available."
        )
    if product["stock"] == "out of stock":
            return f"Sorry, {product['name']} is currently out of stock."
    
    cart = _get_cart(session_id)


    if product_id in cart:
        cart[product_id]["quantity"] = quantity
        action = "Updated"
    else:
        cart[product_id] = {
            "product_id": product_id,
            "name": product["name"],
            "price": product["price"],
            "quantity": quantity,
        }

        action = "Added"

    item = cart[product_id]
    total = _cart_total(cart)
    count = _item_count(cart)

    return (
        f"{action} {item['quantity']}× {item['name']} "
        f"(${item['price']:.2f} each) to your cart.\n"
        f"Cart total: ${total:.2f} "
        f"({count} item{'s' if count != 1 else ''})"
    )

    

async def show_cart(session_id: str = "default") -> str:
    """Show the customer's current cart contents and total."""
    log.info("show_cart", session=session_id)
 
    cart = _get_cart(session_id)
    if not cart:
        return "Your cart is empty. Would you like me to help you find something?"
 
    lines = ["Your cart:"]
    for item in cart.values():
        subtotal = round(item["price"] * item["quantity"], 2)
        lines.append(
            f"  • {item['quantity']}× {item['name']} "
            f"— ${item['price']:.2f} each = ${subtotal:.2f}"
        )
 
    total = _cart_total(cart)
    count = _item_count(cart)
    lines.append(f"\nTotal: ${total:.2f} ({count} item{'s' if count != 1 else ''})")
    lines.append("Ready to checkout whenever you are!")
    return "\n".join(lines)


async def remove_from_cart(product_id: int,session_id: str = "default") -> str:
    """Remove a product from the cart by its ID."""
    log.info("remove_from_cart", product_id=product_id, session=session_id)
 
    cart = _get_cart(session_id)
    if product_id not in cart:
        return (
            f"Product ID {product_id} isn't in your cart. "
            "Say 'show my cart' to see what's in it."
        )
 
    name = cart[product_id]["name"]
    del cart[product_id]
 
    if not cart:
        return f"Removed {name}. Your cart is now empty."
 
    total = _cart_total(cart)
    return f"Removed {name} from your cart. New total: ${total:.2f}"

    


