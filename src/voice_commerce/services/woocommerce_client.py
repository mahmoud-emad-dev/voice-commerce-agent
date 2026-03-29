from __future__ import annotations
from typing import Any
import asyncio

import structlog
import httpx


from voice_commerce.config.settings import settings
from voice_commerce.models.product import Product

log = structlog.get_logger(__name__)


# Module-level reference to the initialized client singleton.
# Set by initialize() when main.py starts up.
# Tools call get_client() to access it.
_client_instance: "WooCommerceClient | None" = None
 
 
def get_client() -> "WooCommerceClient":
    """
    Return the initialized WooCommerceClient singleton.
 
    Called by product_tools.py and cart_tools.py.
    Raises RuntimeError if the client hasn't been initialized yet
    (means initialize() wasn't called in lifespan — programming error).
    """
    if _client_instance is None:
        raise RuntimeError(
            "WooCommerceClient not initialized. "
            "Ensure settings.is_woocommerce_configured is True "
            "and WooCommerceClient.initialize() was called in lifespan."
        )
    return _client_instance

class WooCommerceClient:
    def __init__(self):
        if not settings.is_woocommerce_configured:
            raise ValueError(
                "WooCommerce is not configured. "
                "Set WC_STORE_URL, WC_CONSUMER_KEY, WC_CONSUMER_SECRET in .env"
            )
        self._http  = httpx.AsyncClient(
            base_url=settings.woocommerce_api_url,
            auth=(settings.wc_consumer_key, settings.wc_consumer_secret),
            timeout=httpx.Timeout(
                connect=10.0,
                read=float(settings.wc_timeout),
                write=10.0,
                pool=5.0,
            ),
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
            ),
            follow_redirects=True,
        )


    # =========================================================================
    # ASYNC CONTEXT MANAGER SUPPORT
    # =========================================================================
    # Allows: async with WooCommerceClient() as client: ...
    # Guarantees the httpx client is closed even if exceptions occur

    async def __aenter__(self) -> "WooCommerceClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        await self._http .aclose()
        log.info("woocommerce_client_closed")



    # =========================================================================
    # PRODUCT OPERATIONS
    # =========================================================================
    async def list_products(
        self,
        per_page: int = 100,
        page: int = 1,
        status: str = "publish",
    ) -> list[Product]:
        """
        Fetch a page of published products from the store.
 
        WooCommerce REST API: GET /wp-json/wc/v3/products
        Documentation: https://woocommerce.github.io/woocommerce-rest-api-docs/#list-all-products
 
        WHY PAGINATION (per_page + page):
            WooCommerce limits responses to 100 products per request.
            Large stores (500+ products) require multiple paginated requests.
            per_page=100 is the maximum — minimises number of requests.
 
            For Phase 7 (RAG catalog sync), we use list_all_products() which
            automatically handles pagination by calling this method repeatedly.
 
        Args:
            per_page: Products per page (max 100, WooCommerce hard limit)
            page:     Page number (1-indexed)
            status:   "publish" to only get live products (not drafts/private)
 
        Returns:
            List of Product objects for this page. Empty list if no products.
        """
        params = {
            "per_page": per_page,
            "page": page,
            "status": status,
            # "orderby": "date" — most recent first (default)
        }
 
        log.debug("woo_list_products", page=page, per_page=per_page)
 
        raw_products = await self._get("/products", params=params)
 
        products = []
        for raw in raw_products:
            try:
                products.append(Product.from_woocommerce(raw))
            except Exception as e:
                # A single malformed product shouldn't stop the whole catalog
                log.warning(
                    "woo_product_parse_error",
                    product_id=raw.get("id"),
                    error=str(e),
                )
 
        log.info("woo_list_products_result", count=len(products), page=page)
        return products

    async def list_all_products(self) -> list[Product]:
        """
        Fetch ALL published products, handling pagination automatically.
 
        Used by the RAG catalog sync on startup (Phase 7).
        Makes as many paginated requests as needed to get every product.
 
        WHY NOT JUST INCREASE per_page INDEFINITELY:
            WooCommerce hard-limits to 100 per page regardless of what you request.
            The only way to get more is to fetch multiple pages.
 
        Performance:
            100 products → 1 request (~200ms)
            500 products → 5 requests, sequential (~1000ms)
            500 products with asyncio.gather → 5 concurrent requests (~300ms)
            We use sequential fetching for simplicity — Phase 7 can optimise
            to concurrent if startup time becomes a problem.
 
        Returns:
            All published products in the store.
        """
        log.info("woo_list_all_products_start")
        all_products: list[Product] = []
        page = 1
 
        while True:
            page_products = await self.list_products(per_page=100, page=page)
 
            if not page_products:
                # Empty page means we've fetched everything
                break
 
            all_products.extend(page_products)
            log.debug("woo_pagination_progress",
                      page=page, fetched_so_far=len(all_products))
 
            if len(page_products) < 100:
                # Last page is incomplete — no more pages
                break
 
            page += 1
 
            # Small delay between pages to be polite to the WooCommerce server
            # Avoids triggering rate limits on shared hosting plans
            await asyncio.sleep(0.1)
 
        log.info("woo_list_all_products_done", total=len(all_products))
        return all_products


    async def get_product(self, product_id: int) -> Product | None:
        """
        Fetch one specific product by its WooCommerce ID.
 
        Used by the get_product_details tool when the user asks for
        details about a specific product they saw in search results.
 
        Returns None if the product doesn't exist (404) rather than raising.
        The tool handles None gracefully with a "not found" message.
 
        Args:
            product_id: The WooCommerce numeric product ID
 
        Returns:
            Product object, or None if not found.
        """
        log.debug("woo_get_product", product_id=product_id)
 
        try:
            raw = await self._get(f"/products/{product_id}")
            # Single product endpoint returns a dict, not a list
            if isinstance(raw, dict) and raw.get("id"):
                return Product.from_woocommerce(raw)
            return None
        except WooCommerceNotFoundError:
            log.debug("woo_product_not_found", product_id=product_id)
            return None
 
    async def search_products(
        self,
        query: str,
        max_price: float | None = None,
        category: str | None = None,
        per_page: int = 10,
    ) -> list[Product]:
        """
        Keyword search via WooCommerce REST API.
 
        NOTE: In Phase 7, this is REPLACED by RAG semantic search (Qdrant).
        The WooCommerce REST API search is simple keyword matching — it doesn't
        understand "something warm for hiking" as a query for jackets.
        RAG vector search understands semantic meaning.
 
        This method remains available as a fallback and for comparison.
 
        Args:
            query:     Search string — WooCommerce matches against name/description
            max_price: Filter to products at or below this price
            category:  Filter by category name/slug
            per_page:  Maximum results to return
 
        Returns:
            List of matching Product objects.
        """
        params: dict[str, Any] = {
            "search": query,
            "per_page": per_page,
            "status": "publish",
        }
 
        if max_price is not None:
            params["max_price"] = max_price
 
        if category is not None:
            # WooCommerce filters by category slug, not name.
            # e.g. "Running Shoes" → "running-shoes"
            params["category"] = category.lower().replace(" ", "-")
 
        log.info("woo_search_products", query=query, max_price=max_price)
        raw_products = await self._get("/products", params=params)
 
        products = []
        for raw in raw_products:
            try:
                products.append(Product.from_woocommerce(raw))
            except Exception as e:
                log.warning("woo_search_parse_error", error=str(e))
 
        log.info("woo_search_result", query=query, count=len(products))
        return products


    # =========================================================================
    # LOW-LEVEL HTTP METHOD
    # =========================================================================

    async def _get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """
        Make an authenticated GET request to the WooCommerce REST API.
 
        All public methods call this. Error handling is centralised here.
 
        Args:
            endpoint: API path relative to base_url (e.g. "/products", "/products/42")
            params:   Query parameters dict
 
        Returns:
            Parsed JSON response (dict or list depending on endpoint)
 
        Raises:
            WooCommerceNotFoundError: for 404 responses
            WooCommerceAPIError:      for other non-2xx responses
            httpx.TimeoutException:   if the request times out
        """
        try:
            response = await self._http.get(endpoint, params=params)
 
            log.debug(
                "woo_http_response",
                endpoint=endpoint,
                status_code=response.status_code,
                response_time_ms=round(response.elapsed.total_seconds() * 1000, 1),
            )
 
            # Raise on HTTP errors (4xx, 5xx)
            if response.status_code == 404:
                raise WooCommerceNotFoundError(
                    f"WooCommerce endpoint not found: {endpoint}"
                )
 
            if response.status_code == 401:
                raise WooCommerceAPIError(
                    "WooCommerce authentication failed. "
                    "Check WC_CONSUMER_KEY and WC_CONSUMER_SECRET in .env"
                )
 
            response.raise_for_status()  # Raises for all other 4xx/5xx
 
            return response.json()
 
        except httpx.TimeoutException as e:
            log.error("woo_request_timeout", endpoint=endpoint, error=str(e))
            raise WooCommerceAPIError(
                f"WooCommerce request timed out after {settings.wc_timeout}s. "
                "The store may be slow or unreachable."
            ) from e
 
        except httpx.ConnectError as e:
            log.error("woo_connect_error", store_url=settings.wc_store_url, error=str(e))
            raise WooCommerceAPIError(
                f"Cannot connect to WooCommerce store at {settings.wc_store_url}. "
                "Check WC_STORE_URL in .env and ensure the store is running."
            ) from e


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================
# Named exceptions instead of generic Exception make error handling cleaner
# and make error messages more informative in logs.
 
class WooCommerceAPIError(Exception):
    """Base exception for all WooCommerce client errors."""
    pass
 
class WooCommerceNotFoundError(WooCommerceAPIError):
    """Raised when the requested resource doesn't exist (404)."""
    pass


# =============================================================================
# SINGLETON LIFECYCLE
# =============================================================================
 
async def initialize() -> WooCommerceClient:
    """
    Create and store the client singleton. Called once in main.py lifespan.
 
    After this, any module can call get_client() to get the shared instance.
    The singleton pattern means all tools share one connection pool —
    efficient and avoids creating/destroying TCP connections per tool call.
 
    Returns the initialized client so main.py can store it on app.state too.
    """
    global _client_instance
    client = WooCommerceClient()
    _client_instance = client
    log.info("woocommerce_client_initialized")
    return client
 
 
async def shutdown() -> None:
    """
    Close the client singleton. Called on application shutdown.
    Closes all pooled HTTP connections gracefully.
    """
    global _client_instance
    if _client_instance is not None:
        await _client_instance.close()
        _client_instance = None
        log.info("woocommerce_client_shutdown")
 