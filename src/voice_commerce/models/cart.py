# src/voice_commerce/models/cart.py
# =======================================================================================
# PURPOSE: Pydantic models to manage the user's shopping cart state.
# WHY THIS FILE EXISTS: Separating the Cart logic from the Product logic prevents 
# circular dependencies and keeps our models strictly focused on single responsibilities.
# THIS FILE IN THE ARCHITECTURE: Used by cart_tools.py to track active sessions.
# =======================================================================================

from __future__ import annotations

from pydantic import BaseModel, Field



class CartItem(BaseModel):
    """
    A single line item in a shopping cart.
    Kept simple — cart persistence comes in Phase 11.
    # WHY we copy fields instead of storing the whole Product: A cart item represents
    # a snapshot in time. We only need the ID, name, and current price to calculate totals.
    """
 
    product_id: int
    name: str
    price: float
    quantity: int = 1
 
    @property
    def subtotal(self) -> float:
        """Price × quantity for this line item."""
        return round(self.price * self.quantity, 2)
 
    def to_display_line(self) -> str:
        """One-line cart summary for Gemini to read aloud."""
        return (
            f"{self.quantity}x {self.name} "
            f"— ${self.price:.2f} each = ${self.subtotal:.2f}"
        )
 
 
class Cart(BaseModel):
    """
    The full shopping cart for one session.
    items is keyed by product_id for O(1) lookup.
    """
 
    session_id: str
    items: dict[int, CartItem] = Field(default_factory=dict)
 
    @property
    def total(self) -> float:
        """Sum of all item subtotals."""
        return round(sum(item.subtotal for item in self.items.values()), 2)
 
    @property
    def item_count(self) -> int:
        """Total number of individual items (sum of quantities)."""
        return sum(item.quantity for item in self.items.values())
 
    def is_empty(self) -> bool:
        return len(self.items) == 0
 
    def to_tool_response(self) -> str:
        """Formatted cart summary for Gemini to read as a tool response."""
        if self.is_empty():
            return "Your cart is empty. Would you like me to help find something?"
 
        lines = ["Your cart:"]
        for item in self.items.values():
            lines.append(f"  {item.to_display_line()}")
        lines.append(f"\nTotal: ${self.total:.2f} ({self.item_count} item{'s' if self.item_count != 1 else ''})")
        lines.append("Ready to checkout when you are!")
        return "\n".join(lines)
