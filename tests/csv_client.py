from __future__ import annotations
import csv
import structlog

log = structlog.get_logger(__name__)

class CSVProductClient:
    """
    A standalone local client that reads products from a CSV file.
    This replaces WooCommerce for instant, offline GitHub demos.
    """
    def __init__(self, csv_path: str = "products.csv"):
        self.csv_path = csv_path
        self._products = []
        self._load_csv()

    def _load_csv(self):
        try:
            with open(self.csv_path, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # We format the dictionary so it looks exactly like what 
                    # the WooCommerce API normally returns. This way, we don't 
                    # have to change any of your RAG or Tool code!
                    self._products.append({
                        "id": int(row.get("id", 0)),
                        "name": row.get("name", ""),
                        "price": row.get("price", "0.00"),
                        "description": row.get("description", ""),
                        "categories": [{"name": row.get("category", "Uncategorized")}],
                        "stock_status": "instock",
                        "stock_quantity": int(row.get("stock", 100)),
                        "permalink": row.get("url", f"http://localhost:8000/product/{row.get('id')}")
                    })
            log.info("csv_store_loaded_successfully", count=len(self._products))
        except Exception as e:
            log.error("csv_store_load_failed", error=str(e))

    async def get_all_products(self) -> list[dict]:
        """Returns all products for the RAG Vector Store to index on startup."""
        return self._products

    async def get_product(self, product_id: int) -> dict | None:
        """Returns a single product's details for the get_product_details tool."""
        for p in self._products:
            if str(p["id"]) == str(product_id):
                return p
        return None