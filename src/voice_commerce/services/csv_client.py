from __future__ import annotations
import csv
import asyncio
from pathlib import Path
from typing import Any

import structlog

from voice_commerce.models.product import Product

log = structlog.get_logger(__name__)

# Resolve path relative to this file: src/voice_commerce/services/ → up 3 → project root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
csv_default_path = str(_PROJECT_ROOT / "tests" / "products.csv")
class CSVAPIError(Exception):
    """Base exception for all CSV client errors."""
    pass

class CSVNotFoundError(CSVAPIError):
    """Raised when the requested product ID doesn't exist."""
    pass

# =============================================================================
# SINGLETON LIFECYCLE (Mimics WooCommerce Client)
# =============================================================================

_client_instance: "CSVProductClient | None" = None

def get_client() -> "CSVProductClient":
    if _client_instance is None:
        raise RuntimeError("CSVProductClient not initialized.")
    return _client_instance

async def initialize(csv_path: str = csv_default_path) -> CSVProductClient:
    global _client_instance
    client = CSVProductClient(csv_path)
    _client_instance = client
    log.info("csv_client_initialized", path=csv_path)
    return client

async def shutdown() -> None:
    global _client_instance
    if _client_instance is not None:
        await _client_instance.close()
        _client_instance = None
        log.info("csv_client_shutdown")

# =============================================================================
# CSV CLIENT CLASS
# =============================================================================

class CSVProductClient:
    def __init__(self, csv_path: str = csv_default_path):
        self.csv_path = csv_path
        # THE FIX: We now store actual Pydantic Product objects, not dictionaries!
        self._products: list[Product] = []
        self._load_csv()

    def _load_csv(self) -> None:
        try:
            with open(self.csv_path, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        product_id = int(row.get("ID", 0))
                    except ValueError:
                        continue 
                    
                    if product_id == 0:
                        continue

                    raw_cats = row.get("Categories", "").split("|")
                    categories = []
                    for cat in raw_cats:
                        if cat.strip():
                            # Note: stores only leaf name. Full path ("Men > Shoes > Running") is intentionally
                            # discarded for CSV simplicity. rag_service._parse_category_path() handles full paths
                            # when WooCommerce is the backend.
                            clean_name = cat.split(">")[-1].strip()
                            if not clean_name:
                                continue
                            categories.append({"id": 0, "name": clean_name, "slug": clean_name.lower()})
                    # Safely handle empty prices from the CSV
                    raw_sale_price = row.get("Sale price", "").strip()
                    raw_reg_price = row.get("Regular price", "").strip()
                    sale_price_safe = raw_sale_price if raw_sale_price else None
                    reg_price_safe = raw_reg_price if raw_reg_price else "0"
                    current_price = raw_sale_price if raw_sale_price else reg_price_safe

                    product_data = {
                        "id": product_id,
                        "name": row.get("Name", "").strip(),
                        "slug": row.get("Name", "").lower().replace(" ", "-"),
                        "price": current_price,
                        "regular_price": reg_price_safe,
                        "sale_price": sale_price_safe,
                        "on_sale": bool(sale_price_safe),
                        "description": row.get("description", ""),
                        "short_description": row.get("Short description", ""),
                        "stock_status": "instock" if row.get("In stock?") == "1" else "outofstock",
                        "stock_quantity": int(row["Stock"]) if row.get("Stock", "").isdigit() else None,
                        "sku": row.get("SKU", ""),
                        "categories": categories,
                        "tags": [{"id": 0, "name": t.strip(), "slug": ""} for t in row.get("Tags", "").split(",") if t.strip()],
                        "images": [{"src": img.strip()} for img in row.get("Images", "https://via.placeholder.com/300").split(",") if img.strip()],
                        "permalink": f"http://localhost:8000/product/{product_id}"
                    }
                    
                    # THE FIX: Convert to Pydantic immediately during load!
                    try:
                        valid_product = Product(**product_data)
                        self._products.append(valid_product)
                    except Exception as e:
                        log.warning("csv_product_validation_failed", product_id=product_id, error=str(e))
                        
            log.info("csv_store_loaded_successfully", product_count=len(self._products))
        except Exception as e:
            log.error("csv_store_load_failed", error=str(e))
            raise

    # THE FIX: Return signatures match WooCommerceClient perfectly
    async def list_all_products(self) -> list[Product]:
        await asyncio.sleep(0.01)
        return self._products

    async def get_product(self, product_id: int) -> Product | None:
        await asyncio.sleep(0.01)
        for p in self._products:
            if p.id == product_id:
                return p
        return None

    async def close(self) -> None:
        self._products.clear()
