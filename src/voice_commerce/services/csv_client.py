from __future__ import annotations

import asyncio
import csv
from pathlib import Path

import structlog

from voice_commerce.config.settings import settings
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

_client_instance: CSVProductClient | None = None
_tenant_clients: dict[str, CSVProductClient] = {}


def _resolve_csv_path(csv_path: str) -> str:
    candidate = Path(str(csv_path or csv_default_path).strip() or csv_default_path)
    if not candidate.is_absolute():
        candidate = _PROJECT_ROOT / candidate
    return str(candidate)


def get_client() -> CSVProductClient:
    """Return the initialized CSV-backed store client."""
    if _client_instance is None:
        raise RuntimeError("CSVProductClient not initialized.")
    return _client_instance


def get_client_for_tenant(tenant_id: str | None = None) -> CSVProductClient:
    """Return the initialized CSV-backed client for one tenant."""
    resolved_tenant_id = (
        str(tenant_id or settings.demo_tenant_id).strip() or settings.demo_tenant_id
    )
    client = _tenant_clients.get(resolved_tenant_id)
    if client is not None:
        return client
    if resolved_tenant_id == settings.demo_tenant_id:
        return get_client()
    raise RuntimeError(f"CSVProductClient not initialized for tenant '{resolved_tenant_id}'.")


async def initialize(csv_path: str = csv_default_path) -> CSVProductClient:
    """Create and store the process-wide CSV client used by the demo."""
    global _client_instance
    client = CSVProductClient(_resolve_csv_path(csv_path))
    _client_instance = client
    _tenant_clients[settings.demo_tenant_id] = client
    log.info("csv_client_initialized", tenant_id=settings.demo_tenant_id, path=client.csv_path)
    return client


async def initialize_tenant_client(tenant_id: str, csv_path: str) -> CSVProductClient:
    """Create or replace the CSV client for one tenant catalog."""
    global _client_instance
    resolved_tenant_id = (
        str(tenant_id or settings.demo_tenant_id).strip() or settings.demo_tenant_id
    )
    client = CSVProductClient(_resolve_csv_path(csv_path))
    previous = _tenant_clients.get(resolved_tenant_id)
    if previous is not None:
        await previous.close()
    _tenant_clients[resolved_tenant_id] = client
    if resolved_tenant_id == settings.demo_tenant_id:
        _client_instance = client
    log.info(
        "csv_tenant_client_initialized",
        tenant_id=resolved_tenant_id,
        path=client.csv_path,
    )
    return client


async def shutdown() -> None:
    """Release the process-wide CSV client during app shutdown."""
    global _client_instance
    for client in list(_tenant_clients.values()):
        await client.close()
    _tenant_clients.clear()
    _client_instance = None
    log.info("csv_client_shutdown")


# =============================================================================
# CSV CLIENT CLASS
# =============================================================================


class CSVProductClient:
    """Small store client that loads products from the demo CSV file."""

    def __init__(self, csv_path: str = csv_default_path):
        """Load the demo catalog into Product models once at startup."""
        self.csv_path = csv_path
        self._products: list[Product] = []
        self._load_csv()

    def _load_csv(self) -> None:
        """Parse the CSV catalog into validated Product instances."""
        try:
            with open(self.csv_path, encoding="utf-8-sig") as f:
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
                            # The demo CSV keeps only the leaf category name.
                            # The live WooCommerce sync preserves the full path.
                            clean_name = cat.split(">")[-1].strip()
                            if not clean_name:
                                continue
                            categories.append(
                                {"id": 0, "name": clean_name, "slug": clean_name.lower()}
                            )
                    # The demo CSV can contain empty price fields, so normalize
                    # them before validating with Pydantic.
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
                        "stock_quantity": int(row["Stock"])
                        if row.get("Stock", "").isdigit()
                        else None,
                        "sku": row.get("SKU", ""),
                        "categories": categories,
                        "tags": [
                            {"id": 0, "name": t.strip(), "slug": ""}
                            for t in row.get("Tags", "").split(",")
                            if t.strip()
                        ],
                        "images": [
                            {"src": img.strip()}
                            for img in row.get("Images", "https://via.placeholder.com/300").split(
                                ","
                            )
                            if img.strip()
                        ],
                        "permalink": f"http://localhost:8000/product/{product_id}",
                    }

                    try:
                        valid_product = Product(**product_data)
                        self._products.append(valid_product)
                    except Exception as e:
                        log.warning(
                            "csv_product_validation_failed", product_id=product_id, error=str(e)
                        )

            log.info("csv_store_loaded_successfully", product_count=len(self._products))
        except Exception as e:
            log.error("csv_store_load_failed", error=str(e))
            raise

    async def list_all_products(self) -> list[Product]:
        """Return the full in-memory catalog."""
        await asyncio.sleep(0.01)
        return self._products

    async def get_product(self, product_id: int) -> Product | None:
        """Return one product by ID from the in-memory demo catalog."""
        await asyncio.sleep(0.01)
        for p in self._products:
            if p.id == product_id:
                return p
        return None

    async def close(self) -> None:
        """Clear the in-memory product cache."""
        self._products.clear()
