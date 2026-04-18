from __future__ import annotations
from typing import Any
from dataclasses import dataclass

import structlog
from google.genai import types

from voice_commerce.core.tools import tool_registry , cart_tools, product_tools
from voice_commerce.models.tool_response import ToolResponse

log = structlog.get_logger(__name__)




# ── Tool map ──────────────────────────────────────────────────────────────────
# Maps Gemini's tool name string → the Python async function to call.
# ALL entries are async — consistent interface regardless of whether the
# function does I/O today (Phase 3: no) or in the future (Phase 6: yes).

@dataclass
class ToolContext:

    session_id: str
    tenant_id:  str | None = None   # Phase 12: multi-tenancy


_TOOLS: dict[str, Any] = {
    "search_products": product_tools.search_products,
    "search_categories": product_tools.search_categories,
    "get_product_details": product_tools.get_product_details,
    "add_to_cart": cart_tools.add_to_cart,
    "show_cart": cart_tools.show_cart,
    "remove_from_cart": cart_tools.remove_from_cart,
}





async def execute(tool_name: str, arguments: dict[str, Any], context: ToolContext) -> ToolResponse:
    """
    Execute a named tool, inject session context, return result string.
 
    Called by voice_websocket_handler when Task B receives a tool_call event.
 
    HOW CONTEXT INJECTION WORKS:
      Gemini sends:  {"query": "running shoes", "max_price": 100}
      We add:        {"session_id": "sess_abc123"}
      Tool receives: (query="running shoes", max_price=100, session_id="sess_abc123")
      Cart tools use session_id to look up the right user's cart.
      Search tools accept it and ignore it (consistent signature).
 
      merged_args = {"session_id": ..., **tool_args}
      tool_args keys win if there's a collision (Gemini's data is authoritative).
    """
    log.info("Executing tool", tool_name=tool_name, arguments=arguments, session=context.session_id)

    if not tool_registry.is_registered(tool_name):
        log.warning("dispatcher_unknown_tool", name=tool_name)
        return ToolResponse.error(
            f"I don't have a '{tool_name}' function. "
            f"Available tools: {', '.join(_TOOLS)}"
        )
    
    merged_args = {"session_id": context.session_id, **arguments}

    log.info(
        "dispatcher_calling",
        tool=tool_name,
        args={k: str(v)[:40] for k, v in arguments.items()},
        session=context.session_id,
    )
    try:
        result: ToolResponse = await _TOOLS[tool_name](**merged_args)
        log.info("dispatcher_done", tool=tool_name, result=result.ai_text)
        return result
    
    except TypeError as exc:
        log.warning("dispatcher_arg_mismatch", tool=tool_name, error=str(exc))
        return ToolResponse.error(f"I had trouble calling {tool_name}. Please try rephrasing.")

    except Exception as exc:
        log.error("dispatcher_error", tool=tool_name, error=str(exc), exc_info=True)
        return ToolResponse.error("Something went wrong. Please try again.")




