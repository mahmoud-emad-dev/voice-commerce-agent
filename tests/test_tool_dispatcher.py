# tests/test_tool_dispatcher.py
# =============================================================================
# PURPOSE:
#   Tests for the tool registry, dispatcher, and all tool implementations.
#
# WHY WE USE ASYNC IN THESE TESTS:
#   Even though our Phase 3 tools just return hardcoded dictionaries, they are
#   defined as `async def` so their signature won't change in Phase 6 when we
#   add real network I/O. Therefore, our tests must use `async def` and `await`.
# =============================================================================

from __future__ import annotations

import pytest

from voice_commerce.core.tools import cart_tools, product_tools
from voice_commerce.core.tools.tool_dispatcher import ToolContext, execute
from voice_commerce.core.tools.tool_registry import (
    get_all_tools,
    get_registered_names,
    is_registered,
)
from voice_commerce.models.product import Product, ProductCategory

# Tell pytest to treat all async def tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


def _product(*, product_id: int, name: str, price: float, category: str) -> Product:
    return Product(
        id=product_id,
        name=name,
        price=price,
        regular_price=price,
        short_description=f"About {name}",
        description=f"Full details for {name}",
        stock_status="instock",
        categories=[ProductCategory(id=1, name=category, slug=category.lower().replace(" ", "-"))],
    )


class FakeStoreClient:
    def __init__(self, products: list[Product]) -> None:
        self._products = {product.id: product for product in products}

    async def get_product(self, product_id: int) -> Product | None:
        return self._products.get(product_id)


class FakeRagService:
    def __init__(self, products: list[Product]) -> None:
        self._products = products
        self.is_ready = True
        self._category_lookup = {
            product.categories[0].name.lower(): product.categories[0].name for product in products
        }

    def resolve_category_name(self, category: str) -> str | None:
        return self._category_lookup.get(category.strip().lower())

    async def search_products(
        self,
        query: str,
        limit: int = 5,
        offset: int = 0,
        max_price: float | None = None,
        category: str | None = None,
    ) -> list[Product]:
        normalized_query = query.strip().lower()
        if normalized_query == "حذاء رياضي":
            normalized_query = "running shoe"

        results = []
        for product in self._products:
            haystack = " ".join(
                [
                    product.name.lower(),
                    product.short_description.lower(),
                    " ".join(product.category_names).lower(),
                ]
            )
            if category and category not in product.category_names:
                continue
            if max_price is not None and product.price > max_price:
                continue
            if any(token in haystack for token in normalized_query.split()):
                results.append(product)

        return results[offset : offset + limit]


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    products = [
        _product(product_id=1, name="Aero Running Shoes", price=89.0, category="Shoes"),
        _product(product_id=2, name="Summit Trail Shoes", price=120.0, category="Shoes"),
        _product(product_id=3, name="Flex Training Gloves", price=35.0, category="Gloves"),
        _product(product_id=4, name="Pulse Headphones", price=149.0, category="Accessories"),
    ]
    store_client = FakeStoreClient(products)
    rag = FakeRagService(products)

    monkeypatch.setattr(product_tools, "get_client", lambda: store_client)
    monkeypatch.setattr(cart_tools, "get_client", lambda: store_client)
    monkeypatch.setattr(product_tools, "get_rag_service", lambda: rag)

    cart_tools._CARTS.clear()
    product_tools._SEARCH_RESULT_CACHE.clear()


# =============================================================================
# Tool Registry Tests (These are sync because the registry is just memory)
# =============================================================================

class TestToolRegistry:

    async def test_get_all_tools_returns_list(self) -> None:
        tools = get_all_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    async def test_all_expected_tools_registered(self) -> None:
        names = get_registered_names()
        expected = [
            "search_products",
            "get_product_details",
            "add_to_cart",
            "show_cart",
            "remove_from_cart",
        ]
        for name in expected:
            assert name in names, f"Expected tool '{name}' not registered"

    async def test_is_registered_true_for_known_tool(self) -> None:
        assert is_registered("search_products") is True
        assert is_registered("add_to_cart") is True

    async def test_is_registered_false_for_unknown_tool(self) -> None:
        assert is_registered("nonexistent_tool") is False
        assert is_registered("") is False
        assert is_registered("SEARCH_PRODUCTS") is False  # case sensitive


# =============================================================================
# Product Tool Tests (Async)
# =============================================================================

class TestSearchProducts:

    async def test_returns_tool_response(self) -> None:
        result = await product_tools.search_products(query="shoes")
        assert result.status == "success"
        assert len(result.ai_text) > 0
        assert result.data["products"]

    async def test_finds_shoes_by_keyword(self) -> None:
        result = await product_tools.search_products(query="shoes")
        assert "Aero Running Shoes" in result.ai_text

    async def test_finds_by_brand_name(self) -> None:
        result = await product_tools.search_products(query="summit")
        assert "Summit Trail Shoes" in result.ai_text

    async def test_no_results_returns_graceful_message(self) -> None:
        result = await product_tools.search_products(query="xyznonexistent123")
        assert result.status == "error"
        assert "didn't find" in result.ai_text.lower() or "no products" in result.ai_text.lower()

    async def test_price_filter_excludes_expensive_items(self) -> None:
        result = await product_tools.search_products(query="headphones", max_price=100)
        assert result.status == "error"

    async def test_price_filter_includes_items_under_limit(self) -> None:
        result = await product_tools.search_products(query="gloves", max_price=50)
        assert result.status == "success"
        assert "Gloves" in result.ai_text or "gloves" in result.ai_text.lower()

    async def test_contains_product_ids(self) -> None:
        result = await product_tools.search_products(query="running shoes")
        assert "ID:" in result.ai_text

    async def test_contains_prices(self) -> None:
        result = await product_tools.search_products(query="shoes")
        assert "$" in result.ai_text

    async def test_arabic_query_finds_results(self) -> None:
        result = await product_tools.search_products(query="حذاء رياضي")
        assert result.status == "success"
        assert result.data["products"]


class TestGetProductDetails:

    async def test_returns_details_for_valid_id(self) -> None:
        result = await product_tools.get_product_details(product_id=1)
        assert result.status == "success"
        assert "Aero Running Shoes" in result.ai_text
        assert "ID" in result.ai_text
        assert "$" in result.ai_text

    async def test_invalid_id_returns_graceful_message(self) -> None:
        result = await product_tools.get_product_details(product_id=99999)
        assert result.status == "error"
        assert "couldn't find" in result.ai_text.lower()

    async def test_all_fake_products_retrievable(self) -> None:
        for i in range(1, 5):
            result = await product_tools.get_product_details(product_id=i)
            assert result.status == "success"


# =============================================================================
# Cart Tool Tests (Async)
# =============================================================================

class TestAddToCart:

    async def test_add_product_returns_confirmation(self) -> None:
        result = await cart_tools.add_to_cart(product_id=1, quantity=1, session_id="t1")
        assert result.status == "success"
        assert "Aero Running Shoes" in result.ai_text
        assert "$" in result.ai_text

    async def test_add_increases_cart_total(self) -> None:
        sid = "test_add_total"
        await cart_tools.add_to_cart(product_id=1, quantity=1, session_id=sid)
        show_result = await cart_tools.show_cart(session_id=sid)
        assert "$89.00" in show_result.ai_text

    async def test_add_same_product_twice_increases_quantity(self) -> None:
        sid = "test_add_qty"
        await cart_tools.add_to_cart(product_id=2, quantity=1, session_id=sid)
        await cart_tools.add_to_cart(product_id=2, quantity=1, session_id=sid)
        show_result = await cart_tools.show_cart(session_id=sid)
        assert "2x" in show_result.ai_text

    async def test_invalid_product_id_returns_error(self) -> None:
        result = await cart_tools.add_to_cart(product_id=99999, quantity=1, session_id="t2")
        assert result.status == "error"
        assert "couldn't find" in result.ai_text.lower()


class TestShowCart:

    async def test_empty_cart_returns_helpful_message(self) -> None:
        result = await cart_tools.show_cart(session_id="empty_cart_test")
        assert result.status == "success"
        assert "empty" in result.ai_text.lower()

    async def test_shows_items_after_adding(self) -> None:
        sid = "test_show_add"
        await cart_tools.add_to_cart(product_id=4, quantity=1, session_id=sid)
        result = await cart_tools.show_cart(session_id=sid)
        assert "Pulse Headphones" in result.ai_text


class TestRemoveFromCart:

    async def test_remove_item_from_cart(self) -> None:
        sid = "test_remove"
        await cart_tools.add_to_cart(product_id=3, quantity=1, session_id=sid)
        result = await cart_tools.remove_from_cart(product_id=3, session_id=sid)
        assert result.status == "success"
        assert "removed" in result.ai_text.lower()

    async def test_remove_nonexistent_item_returns_error(self) -> None:
        result = await cart_tools.remove_from_cart(product_id=1, session_id="test_no_item")
        assert result.status == "error"
        assert (
            "isn't in your cart" in result.ai_text.lower()
            or "not found" in result.ai_text.lower()
        )


# =============================================================================
# Dispatcher Tests (Async)
# =============================================================================

class TestToolDispatcher:

    def _ctx(self, session_id: str = "test_dispatch") -> ToolContext:
        return ToolContext(session_id=session_id)

    async def test_dispatch_search_products(self) -> None:
        result = await execute("search_products", {"query": "shoes"}, self._ctx())
        assert result.status == "success"
        assert len(result.ai_text) > 0

    async def test_dispatch_add_to_cart(self) -> None:
        result = await execute(
            "add_to_cart",
            {"product_id": 1, "quantity": 1},
            self._ctx("test_dispatch_cart"),
        )
        assert result.status == "success"
        assert "added" in result.ai_text.lower()

    async def test_dispatch_unknown_tool_returns_graceful_error(self) -> None:
        result = await execute("definitely_not_a_real_tool", {}, self._ctx())
        assert result.status == "error"
        assert "i don't have" in result.ai_text.lower() or "unknown" in result.ai_text.lower()

    async def test_dispatcher_injects_session_id_into_cart_tools(self) -> None:
        sid = "test_injection"
        # FIXED TYPO HERE: Was {"product_id=2", ...} which created a python Set instead of a Dict!
        await execute("add_to_cart", {"product_id": 2, "quantity": 1}, self._ctx(sid))
        
        result = await execute("show_cart", {}, self._ctx(sid))
        assert "Summit Trail Shoes" in result.ai_text
