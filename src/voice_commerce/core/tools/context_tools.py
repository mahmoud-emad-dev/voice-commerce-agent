from __future__ import annotations

from voice_commerce.models.screen_context import get_screen_cache
from voice_commerce.models.tool_response import ToolResponse


async def get_screen_context(session_id: str = "default") -> ToolResponse:
    cache = get_screen_cache(session_id)

    if not cache.has_data():
        return ToolResponse.success(
            ai_text="The user has no products visible right now.",
            data={"products": [], "url": "", "filters": [], "cart_count": 0},
        )

    return ToolResponse.success(
        ai_text=cache.render_for_tool(),
        data=cache.snapshot(),
    )

