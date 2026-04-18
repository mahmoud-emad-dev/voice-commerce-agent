# src/voice_commerce/models/product.py
# =============================================================================
# PURPOSE: Pydantic models representing a single WooCommerce product and its metadata.
# WHY THIS FILE EXISTS: Raw WooCommerce REST API responses are messy (HTML in descriptions, 
# string prices, missing fields). This boundary layer scrubs the data clean so the rest 
# of our app (and the AI) only deals with safe, validated, perfectly typed Python objects.
# THIS FILE IN THE ARCHITECTURE: Used by woocommerce_client.py to parse responses, 
# and by product_tools.py to format data for the Gemini AI.
# =============================================================================
from __future__ import annotations
import html
import re
from typing import Any


from pydantic import BaseModel, Field, field_validator


class ProductCategory(BaseModel):
    """A single category a product belongs to."""
    id: int = 0
    name: str
    slug: str
    
class ProductTag(BaseModel):
    """A single tag attached to a product."""
    id: int = 0
    name: str
    slug: str = ""

class Product(BaseModel):
    """
    A single WooCommerce product, normalised from the REST API response.

    All fields have defaults — so partial data (e.g. from search results
    that return fewer fields than single-product detail calls) never fails
    to parse. You get what the API gives; missing fields fall back to defaults.
    """

# ── Identity ──────────────────────────────────────────────────────────────
    id: int
    # The WooCommerce numeric product ID. Used in every tool call that
    # references a specific product (add_to_cart, get_product_details).
 
    name: str
    # The product's display name. Shown to customers.
 
    slug: str = ""
    # URL-safe version of the name. Used to construct product page URLs.
# ── Pricing ───────────────────────────────────────────────────────────────
    price: float = 0.0
    # Current selling price (may be the sale price if on_sale is True).
    # WooCommerce returns this as a string ("129.99") — Pydantic coerces to float.
 
    regular_price: float = 0.0
 
    sale_price: float | None = None
 
    on_sale: bool = False
    # True when a sale price is active. Gemini uses this in responses:
    # "The Nike Air Zoom is currently on sale — $129 down from $149."
 
# ── Description ───────────────────────────────────────────────────────────
    description: str = ""
    # Full HTML description from WooCommerce. We strip HTML tags on parse.
    # Used in RAG embeddings (Phase 7) and detail tool responses.
 
    short_description: str = ""
    # Brief plain-text summary. Used in search result summaries.
 
# ── Stock ─────────────────────────────────────────────────────────────────
    stock_status: str = "instock"
    # "instock", "outofstock", or "onbackorder".
 
    stock_quantity: int | None = None
    # Exact count if "Manage stock" is enabled in WooCommerce.
 
# ── Classification ────────────────────────────────────────────────────────
    # WHY default_factory: If a product has no categories, Pydantic will safely assign 
    # an empty list `[]` instead of `None`, preventing "NoneType has no attribute append" errors.
    categories: list[ProductCategory] = Field(default_factory=list)
    # e.g. [{"name": "Running Shoes"}, {"name": "Shoes"}]
 
    tags: list[ProductTag] = Field(default_factory=list)
    # e.g. [{"name": "nike"}, {"name": "lightweight"}]
 
# ── Metadata ──────────────────────────────────────────────────────────────
    sku: str = "" 
    weight: str = "" 
    permalink: str = ""
    thumbnail: str = ""
    images: list[dict] = Field(default_factory=list)
    # Full URL to the product page on the WooCommerce store.
    # Used in browser actions (Phase 8) to link customers to the product page.


    # =========================================================================
    # VALIDATORS
    # =========================================================================
    # Validators run automatically when a Product is created from data.
    # They normalise and sanitise values before they're stored.
 
    @field_validator("price", "regular_price", mode="before")
    @classmethod
    def parse_price_string(cls, v: Any) -> float:
        """
        Convert price strings to float.
 
        WooCommerce returns prices as strings: "129.99", "0", "".
        Pydantic's default coercion handles most cases, but empty string
        "" would raise a ValueError — we convert it to 0.0 explicitly.
 
        mode="before" means this runs BEFORE Pydantic's own type coercion,
        so we get the raw value from the JSON (a string) not a float.
        """
        if v == "" or v is None:
            return 0.0
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0
 
    @field_validator("description", "short_description", mode="before")
    @classmethod
    def strip_html(cls, v: object) -> str:
        """
        Strip HTML tags from description fields.
 
        WooCommerce stores descriptions as HTML:
          "<p>Lightweight running shoe with <strong>React foam</strong>.</p>"
 
        We want plain text for:
        1. Gemini's spoken responses — HTML tags sound weird when read aloud
        2. RAG embeddings (Phase 7) — clean text makes better semantic vectors
 
        Simple approach: remove all <tag> patterns.
        Not perfect (doesn't decode HTML entities like &amp;) but good enough
        for product descriptions. Phase 7 can add html2text if needed.
        """
        if not v:
            return ""
        # Remove all HTML tags (anything between < and >)
        text = re.sub(r"<[^>]+>", "", str(v))
        # Collapse multiple whitespace/newlines to single space
        text = re.sub(r"\s+", " ", text).strip()
        return text
 
    @field_validator("stock_status", mode="before")
    @classmethod
    def normalise_stock_status(cls, v: object) -> str:
        """Ensure stock_status is always a lowercase string."""
        return str(v).lower() if v else "instock"
 
    # =========================================================================
    # COMPUTED PROPERTIES
    # =========================================================================
 
    @property
    def is_in_stock(self) -> bool:
        """True if the product can be added to cart."""
        return self.stock_status == "instock"
 
    @property
    def display_price(self) -> str:
        """
        Human-readable price string for Gemini tool responses.
 
        Examples:
          "$129.99"               (normal price)
          "$99.99 (was $149.99)" (on sale)
        """
        price_str = f"${self.price:.2f}"
        if self.on_sale and self.regular_price > self.price:
            price_str += f" (was ${self.regular_price:.2f})"
        return price_str
 
    @property
    def category_names(self) -> list[str]:
        """Category names as a plain list for display and embedding."""
        return [c.name for c in self.categories]
 
    @property
    def tag_names(self) -> list[str]:
        """Tag names as a plain list for display and embedding."""
        return [t.name for t in self.tags]
 
    def to_embedding_text(self) -> str:
        """
        Build the text string that gets embedded into a vector for RAG search.
 
        WHY RICH TEXT (not just product name):
            The embedding model converts this string to a vector that represents
            its semantic meaning. More context = better semantic matches.
 
            "Nike Air Zoom" alone:
                → matches "nike" and "air" and "zoom" — too narrow
 
            Full embedding text:
                → also matches "running", "lightweight", "road running",
                  "daily training", "breathable" — much better recall
 
        The structure (Name. Description. Category. Tags.) is consistent
        across all products so the embedding space is comparable.
        Used in Phase 7 (rag_service.py) when indexing products into Qdrant.
        """
        clean_short_description = html.unescape(self.short_description).strip()
        clean_description = html.unescape(self.description).strip()

        parts = [self.name]

        if clean_short_description:
            parts.append(f"Summary: {clean_short_description}")
        if clean_description and clean_description != clean_short_description:
            # Use first 300 chars of full description — enough for semantics
            parts.append(f"Details: {clean_description[:300]}")
        if self.category_names:
            parts.append(f"Category: {', '.join(self.category_names)}")
        if self.tag_names:
            parts.append(f"Tags: {', '.join(self.tag_names)}")

        return ". ".join(parts)
 
    def to_tool_summary(self) -> str:
        """
        One-line summary for search result lists (Gemini reads these aloud).
 
        Concise enough that Gemini doesn't read a wall of text per product.
        Includes the ID so Gemini can reference it in add_to_cart calls.
        """
        stock = "In stock" if self.is_in_stock else "Out of stock"
        categories = ", ".join(self.category_names[:2])  # max 2 categories
        return (
            f"• {self.name} — {self.display_price} — {stock} — ID:{self.id}"
            + (f"\n  {self.short_description}" if self.short_description else "")
            + (f" [{categories}]" if categories else "")
        )
 
    def to_tool_detail(self) -> str:
        """
        Full detail string for get_product_details tool responses.
        More verbose than to_tool_summary — used when user asks for specifics.
        """
        lines = [
            f"Product: {self.name}",
            f"ID: {self.id}",
            f"Price: {self.display_price}",
            f"Stock: {'In stock' if self.is_in_stock else 'Out of stock'}"
            + (f" ({self.stock_quantity} available)" if self.stock_quantity else ""),
        ]
        if self.category_names:
            lines.append(f"Categories: {', '.join(self.category_names)}")
        if self.tag_names:
            lines.append(f"Tags: {', '.join(self.tag_names)}")
        if self.sku:
            lines.append(f"SKU: {self.sku}")
        if self.weight:
            lines.append(f"Weight: {self.weight}")
        if self.description:
            lines.append(f"Description: {self.description[:400]}")
        if self.permalink:
            lines.append(f"URL: {self.permalink}")
        return "\n".join(lines)
 
    def to_tool_response(self , detailed :bool = False) -> dict[str, Any]:
        """
        Return a dictionary representation of the product for tool responses.
        ai_text as for gemini and rest for browser Actions on UI.
        """
        return {
            "ai_text":  self.to_tool_detail() if detailed else self.to_tool_summary() ,
            "data": {
                "id": self.id,
                "name": self.name,
                "display_price": self.display_price,
                "is_in_stock": self.is_in_stock,
                "permalink": self.permalink,
            }
        }

    # =========================================================================
    # CLASS METHODS — parsing from external sources
    # =========================================================================
 
    @classmethod
    def from_woocommerce(cls, data: dict) -> "Product":
        """
        Parse a raw WooCommerce REST API product dict into a Product model.
 
        The WooCommerce API response has inconsistent field names and
        nested structures. This method handles the translation:
          "regular_price" (string) → regular_price (float)
          "categories"    (list)   → list[ProductCategory]
          etc.
 
        WHY A CLASSMETHOD (not just Product(**data)):
            The API response keys don't all map cleanly to our field names.
            Some need transformation (price string → float).
            Some are nested differently (images[0].src → no direct mapping).
            A classmethod centralises all the WooCommerce-specific parsing
            knowledge in one place.
 
        Args:
            data: Raw dict from WooCommerce REST API GET /products response
 
        Returns:
            A validated Product instance
        """
        return cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            slug=data.get("slug", ""),
 
            # Prices come as strings from WooCommerce ("129.99")
            # The price validator coerces them to float
            price=data.get("price", "0"),
            regular_price=data.get("regular_price", "0"),
            sale_price=data.get("sale_price") or None,
            on_sale=data.get("on_sale", False),
 
            # Descriptions come as HTML — the validator strips tags
            description=data.get("description", ""),
            short_description=data.get("short_description", ""),
 
            stock_status=data.get("stock_status", "instock"),
            stock_quantity=data.get("stock_quantity"),
 
            # Categories and tags are lists of {id, name, slug} dicts
            categories=[
                ProductCategory(**cat)
                for cat in data.get("categories", [])
                if isinstance(cat, dict)
            ],
            tags=[
                ProductTag(**tag)
                for tag in data.get("tags", [])
                if isinstance(tag, dict)
            ],
 
            sku=data.get("sku", ""),
            weight=data.get("weight", ""),
            permalink=data.get("permalink", ""),
            # thumbnail=(
            #     data.get("images", [{}])[0].get("src", "")
            #     if data.get("images") and isinstance(data.get("images")[0], dict)
            #     else ""
            # ),
        )
    

