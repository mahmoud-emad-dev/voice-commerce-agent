# tests/test_woocommerce_client.py
# =============================================================================
# PURPOSE:
#   Test the WooCommerce data models and the HTTP client.
#
# TESTING STRATEGY:
#   1. Model Tests: Ensure Pydantic scrubs raw JSON properly (pure unit tests).
#   2. Client Unit Tests: Use httpx.MockTransport to fake internet responses.
#   3. Integration Tests: Real API calls marked with @pytest.mark.integration.
# =============================================================================

from __future__ import annotations
import pytest
import httpx
import datetime  # <-- NEW: Needed for our fake stopwatch

from voice_commerce.models.product import Product
from voice_commerce.services.woocommerce_client import (
    WooCommerceClient,
    WooCommerceNotFoundError,
    WooCommerceAPIError
)
from voice_commerce.config.settings import settings

# =============================================================================
# 1. SAMPLE MOCK DATA
# =============================================================================

RAW_PRODUCT = {
    "id": 42,
    "name": "Test Running Shoe",
    "price": "99.99",
    "regular_price": "129.99",
    "on_sale": True,
    "description": "<p>A <strong>superb</strong> lightweight shoe.</p><br />",
    "short_description": "Lightweight shoe.",
    "stock_status": "instock",
    "stock_quantity": 10,
    "categories": [{"id": 1, "name": "Running", "slug": "running"}],
    "sku": "TEST-SHOE-01"
}


# =============================================================================
# 2. MODEL UNIT TESTS (The Data Boundary)
# =============================================================================

def test_product_model_parsing():
    """Ensure the Pydantic model scrubs HTML and fixes string prices."""
    product = Product.from_woocommerce(RAW_PRODUCT)
    
    assert product.id == 42
    assert product.name == "Test Running Shoe"
    
    # Check Price Coercion (Strings -> Floats)
    assert product.price == 99.99
    assert product.regular_price == 129.99
    assert product.on_sale is True
    
    # Check HTML Stripping
    assert product.description == "A superb lightweight shoe."
    assert "<p>" not in product.description
    
    # Check Categories
    assert len(product.categories) == 1
    assert product.categories[0].name == "Running"

def test_product_model_defaults():
    """Ensure partial or missing data doesn't crash the model."""
    empty_product = Product.from_woocommerce({"id": 1, "name": "Ghost Item"})
    
    assert empty_product.price == 0.0
    assert empty_product.description == ""
    assert empty_product.is_in_stock is True  # Defaults to true if missing
    assert empty_product.categories == []


# =============================================================================
# 3. CLIENT UNIT TESTS (Mocking the Internet)
# =============================================================================

@pytest.mark.asyncio
async def test_client_search_products():
    """Test that search_products properly parses the list of results."""
    
    # 1. Create a fake internet response
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[RAW_PRODUCT, RAW_PRODUCT], request=request)        
    fake_transport = httpx.MockTransport(mock_handler)    
    # 2. Inject the fake internet into our client
    client = WooCommerceClient()
    client._http = httpx.AsyncClient(transport=fake_transport, base_url="https://test.com")
    
    # 3. Run the search
    results = await client.search_products("shoe")
    
    # 4. Verify it handled the fake response correctly
    assert len(results) == 2
    assert results[0].id == 42
    assert isinstance(results[0], Product)

@pytest.mark.asyncio
async def test_client_get_product_not_found():
    """Test that a 404 gracefully returns None instead of crashing."""
    
    def mock_404(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": "woocommerce_rest_product_invalid_id"}, request=request)
        
    fake_transport = httpx.MockTransport(mock_404)
    client = WooCommerceClient()
    client._http = httpx.AsyncClient(transport=fake_transport, base_url="https://test.com")
    
    # The client._get() will raise a WooCommerceNotFoundError
    # But client.get_product() should catch it and return None
    result = await client.get_product(99999)
    assert result is None

@pytest.mark.asyncio
async def test_client_auth_failure():
    """Test that a 401 Unauthorized properly raises an API Error."""
    
    def mock_401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "woocommerce_rest_cannot_view"}, request=request)
        
    fake_transport = httpx.MockTransport(mock_401)
    client = WooCommerceClient()
    client._http = httpx.AsyncClient(transport=fake_transport, base_url="https://test.com")
    
    with pytest.raises(WooCommerceAPIError) as exc_info:
        await client.list_products()
        
    assert "authentication failed" in str(exc_info.value).lower()


# =============================================================================
# 4. INTEGRATION TESTS (The Real Internet)
# =============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_woocommerce_connection():
    """
    REAL API TEST: Reaches out to the actual store.
    Run with: uv run pytest tests/ -m integration -v
    """
    if not settings.is_woocommerce_configured:
        pytest.skip("WooCommerce credentials not found in .env. Skipping live test.")
        
    # We use the real async context manager here to open and close the pool
    async with WooCommerceClient() as client:
        products = await client.list_products(per_page=3)
        
        assert isinstance(products, list)
        if len(products) > 0:
            assert isinstance(products[0], Product)
            assert products[0].id > 0