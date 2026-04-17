from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScreenSnapshot:
    url: str = ""
    filters: list[str] = field(default_factory=list)
    cart_count: int = 0
    products: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = 0.0
    version: int = 0


class ScreenContextCache:
    """Per-session latest screen state. Backend stores, Gemini pulls via tool."""

    def __init__(self) -> None:
        self._snap = ScreenSnapshot()

    def update(self, page: dict[str, Any], products: list[dict[str, Any]]) -> None:
        self._snap = ScreenSnapshot(
            url=str(page.get("url", "")),
            filters=list(page.get("active_filters", []) or []),
            cart_count=int(page.get("cart_count", 0) or 0),
            products=list(products[:30]),
            updated_at=time.time(),
            version=self._snap.version + 1,
        )

    def has_data(self) -> bool:
        return self._snap.version > 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "url": self._snap.url,
            "filters": self._snap.filters,
            "cart_count": self._snap.cart_count,
            "products": self._snap.products,
            "version": self._snap.version,
        }

    def render_for_tool(self) -> str:
        if not self.has_data():
            return "User has no products visible right now."

        s = self._snap
        lines = [
            f"URL: {s.url}",
            f"Filters: {', '.join(s.filters) if s.filters else 'None'}",
            f"Cart: {s.cart_count} items",
        ]
        if s.products:
            lines.append("VISIBLE PRODUCTS (numbered):")
            for i, p in enumerate(s.products, 1):
                lines.append(
                    f"{i}. ID:{p.get('id')} | {p.get('name')} | ${p.get('price')}"
                )
        return "\n".join(lines)

    def render_short_hint(self) -> str:
        if not self.has_data():
            return ""
        s = self._snap
        filters = ", ".join(s.filters) if s.filters else "no filters"
        return f"[Screen: {filters}, cart={s.cart_count}, {len(s.products)} visible]"


_CACHES: dict[str, ScreenContextCache] = {}


def get_screen_cache(session_id: str) -> ScreenContextCache:
    if session_id not in _CACHES:
        _CACHES[session_id] = ScreenContextCache()
    return _CACHES[session_id]

