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
    is_registered
)

# Tell pytest to treat all async def tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


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

    async def test_returns_string(self) -> None:
        # WHY AWAIT: Product tools are async, we must await to get the string
        result = await product_tools.search_products(query="shoes")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_finds_shoes_by_keyword(self) -> None:
        result = await product_tools.search_products(query="shoes")
        assert "Nike" in result or "Adidas" in result

    async def test_finds_by_brand_name(self) -> None:
        result = await product_tools.search_products(query="adidas")
        assert "Adidas" in result

    async def test_no_results_returns_graceful_message(self) -> None:
        result = await product_tools.search_products(query="xyznonexistent123")
        assert "didn't find" in result.lower() or "no products" in result.lower()
        assert len(result) > 10

    async def test_price_filter_excludes_expensive_items(self) -> None:
        result = await product_tools.search_products(query="headphones", max_price=100)
        assert "Sony" not in result or "couldn't find" in result.lower()

    async def test_price_filter_includes_items_under_limit(self) -> None:
        result = await product_tools.search_products(query="gloves", max_price=50)
        assert "Gloves" in result or "gloves" in result.lower()

    async def test_contains_product_ids(self) -> None:
        result = await product_tools.search_products(query="running shoes")
        assert "ID:" in result

    async def test_contains_prices(self) -> None:
        result = await product_tools.search_products(query="shoes")
        assert "$" in result

    async def test_arabic_query_finds_results(self) -> None:
        # ── Phase 7: Semantic matching will make this actually return shoes ──
        result = await product_tools.search_products(query="حذاء رياضي")
        assert isinstance(result, str)


class TestGetProductDetails:

    async def test_returns_details_for_valid_id(self) -> None:
        result = await product_tools.get_product_details(product_id=1)
        assert "Nike" in result
        assert "ID" in result
        assert "$" in result

    async def test_invalid_id_returns_graceful_message(self) -> None:
        result = await product_tools.get_product_details(product_id=99999)
        assert "couldn't find" in result.lower()

    async def test_all_fake_products_retrievable(self) -> None:
        for i in range(1, 7):
            result = await product_tools.get_product_details(product_id=i)
            assert "couldn't find" not in result.lower()


# =============================================================================
# Cart Tool Tests (Async)
# =============================================================================

class TestAddToCart:

    async def test_add_product_returns_confirmation(self) -> None:
        result = await cart_tools.add_to_cart(product_id=1, quantity=1, session_id="t1")
        assert isinstance(result, str)
        assert "Nike" in result
        assert "$" in result

    async def test_add_increases_cart_total(self) -> None:
        sid = "test_add_total"
        await cart_tools.add_to_cart(product_id=1, quantity=1, session_id=sid)
        show_result = await cart_tools.show_cart(session_id=sid)
        assert "129" in show_result or "130" in show_result

    async def test_add_same_product_twice_increases_quantity(self) -> None:
        sid = "test_add_qty"
        await cart_tools.add_to_cart(product_id=2, quantity=1, session_id=sid)
        await cart_tools.add_to_cart(product_id=2, quantity=1, session_id=sid)
        show_result = await cart_tools.show_cart(session_id=sid)
        assert "2×" in show_result

    async def test_invalid_product_id_returns_error(self) -> None:
        result = await cart_tools.add_to_cart(product_id=99999, quantity=1, session_id="t2")
        assert "couldn't find" in result.lower()


class TestShowCart:

    async def test_empty_cart_returns_helpful_message(self) -> None:
        result = await cart_tools.show_cart(session_id="empty_cart_test")
        assert "empty" in result.lower()

    async def test_shows_items_after_adding(self) -> None:
        sid = "test_show_add"
        await cart_tools.add_to_cart(product_id=4, quantity=1, session_id=sid)
        result = await cart_tools.show_cart(session_id=sid)
        assert "Sony" in result


class TestRemoveFromCart:

    async def test_remove_item_from_cart(self) -> None:
        sid = "test_remove"
        await cart_tools.add_to_cart(product_id=3, quantity=1, session_id=sid)
        result = await cart_tools.remove_from_cart(product_id=3, session_id=sid)
        assert "Removed" in result or "removed" in result.lower()

    async def test_remove_nonexistent_item_returns_error(self) -> None:
        result = await cart_tools.remove_from_cart(product_id=1, session_id="test_no_item")
        assert "isn't in your cart" in result.lower() or "not found" in result.lower()


# =============================================================================
# Dispatcher Tests (Async)
# =============================================================================

class TestToolDispatcher:

    def _ctx(self, session_id: str = "test_dispatch") -> ToolContext:
        return ToolContext(session_id=session_id)

    async def test_dispatch_search_products(self) -> None:
        result = await execute("search_products", {"query": "shoes"}, self._ctx())
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_dispatch_add_to_cart(self) -> None:
        result = await execute(
            "add_to_cart",
            {"product_id": 1, "quantity": 1},
            self._ctx("test_dispatch_cart"),
        )
        assert isinstance(result, str)
        assert "Nike" in result or "added" in result.lower()

    async def test_dispatch_unknown_tool_returns_graceful_error(self) -> None:
        result = await execute("definitely_not_a_real_tool", {}, self._ctx())
        assert isinstance(result, str)
        assert "I don't have" in result or "unknown" in result.lower()

    async def test_dispatcher_injects_session_id_into_cart_tools(self) -> None:
        sid = "test_injection"
        # FIXED TYPO HERE: Was {"product_id=2", ...} which created a python Set instead of a Dict!
        await execute("add_to_cart", {"product_id": 2, "quantity": 1}, self._ctx(sid))
        
        result = await execute("show_cart", {}, self._ctx(sid))
        assert "Adidas" in result # product_id 2 is Adidas in fake data