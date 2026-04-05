# src/voice_commerce/models/tool_response.py
# =============================================================================
# PURPOSE: The strict, unified data contract for all Gemini tool returns.
# WHY THIS FILE EXISTS: Prevents bugs caused by loose dictionaries. Guarantees 
# the Action Dispatcher and Gemini always receive exactly what they expect.
# =============================================================================

from __future__ import annotations
from typing import Any , Literal

from pydantic import BaseModel , Field


class ToolResponse(BaseModel):
    """
    Every tool in core/tools/ MUST return this model.
    """
    status: Literal["success", "error"]
    ai_text: str = Field(
        ..., 
        description="The exact human-readable text returned to Gemini and should read out loud."
    )
    # The flexible "backpack" for UI data (product_id, cart_count, etc.)
    data: dict[str, Any] = Field(default_factory=dict)

    # ── Helper Methods for quick creation ─────────────────────────────────────
    @classmethod
    def success(cls, ai_text: str, data: dict[str, Any] | None = None) -> "ToolResponse":
            """Shortcut to create a success response."""
            return cls(status="success", ai_text=ai_text, data=data or {})
    @classmethod
    def error(cls, error_msg: str, data: dict[str, Any] | None = None) -> "ToolResponse":
        """Shortcut to create an error response."""
        return cls(status="error", ai_text=error_msg, data=data or {})