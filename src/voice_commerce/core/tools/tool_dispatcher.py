from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import structlog

from voice_commerce.core.tools import cart_tools, checkout_tools, product_tools, tool_registry
from voice_commerce.models.tool_response import ToolResponse
from voice_commerce.observability.metrics import observe_tool_call
from voice_commerce.observability.tracing import get_tracer
from voice_commerce.observability.usage import record_tool_call

log = structlog.get_logger(__name__)

_TOOL_EXECUTION_TIMEOUT_S = 5




# ── Tool map ──────────────────────────────────────────────────────────────────
# Maps Gemini's tool name string → the Python async function to call.
# ALL entries are async — consistent interface regardless of whether the
# function does I/O today (Phase 3: no) or in the future (Phase 6: yes).

@dataclass
class ToolContext:

    session_id: str
    tenant_id: str | None = None


_TOOLS: dict[str, Any] = {
    "search_products": product_tools.search_products,
    "search_categories": product_tools.search_categories,
    "get_product_details": product_tools.get_product_details,
    "add_to_cart": cart_tools.add_to_cart,
    "show_cart": cart_tools.show_cart,
    "remove_from_cart": cart_tools.remove_from_cart,
    "begin_checkout": checkout_tools.begin_checkout,
    "set_checkout_option": checkout_tools.set_checkout_option,
    "confirm_checkout": checkout_tools.confirm_checkout,
    "cancel_checkout": checkout_tools.cancel_checkout,
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
    started_at = time.perf_counter()

    if not tool_registry.is_registered(tool_name):
        log.warning("dispatcher_unknown_tool", name=tool_name)
        observe_tool_call(
            context.tenant_id,
            tool_name,
            time.perf_counter() - started_at,
            status="unknown_tool",
        )
        return ToolResponse.error(
            f"I don't have a '{tool_name}' function. "
            f"Available tools: {', '.join(_TOOLS)}"
        )
    
    merged_args = {"session_id": context.session_id, "tenant_id": context.tenant_id, **arguments}

    log.info(
        "dispatcher_calling",
        tool=tool_name,
        args={k: str(v)[:40] for k, v in arguments.items()},
        session=context.session_id,
        tenant_id=context.tenant_id,
    )
    try:
        async with asyncio.timeout(_TOOL_EXECUTION_TIMEOUT_S):
            result: ToolResponse = await _TOOLS[tool_name](**merged_args)
        record_tool_call(context.tenant_id, tool_name)
        get_tracer().record_observation(
            f"tool_{tool_name}",
            as_type="tool",
            session_id=context.session_id,
            tenant_id=context.tenant_id,
            input_payload=arguments,
            output_payload={"status": result.status},
            metadata={"tool_name": tool_name, "status": result.status},
            model=None,
        )
        observe_tool_call(
            context.tenant_id,
            tool_name,
            time.perf_counter() - started_at,
            status=result.status,
        )
        log.info("dispatcher_done", tool=tool_name, result=result.ai_text)
        return result
    
    except TimeoutError:
        record_tool_call(context.tenant_id, tool_name)
        get_tracer().record_event(
            "tool_timeout",
            session_id=context.session_id,
            tenant_id=context.tenant_id,
            input_payload=arguments,
            metadata={"tool_name": tool_name},
            level="ERROR",
        )
        observe_tool_call(
            context.tenant_id,
            tool_name,
            time.perf_counter() - started_at,
            status="timeout",
        )
        log.error(
            "dispatcher_timeout",
            tool=tool_name,
            timeout_s=_TOOL_EXECUTION_TIMEOUT_S,
            session=context.session_id,
        )
        return ToolResponse.error("That request took too long. Please try again.")
    
    except TypeError as exc:
        record_tool_call(context.tenant_id, tool_name)
        get_tracer().record_event(
            "tool_arg_mismatch",
            session_id=context.session_id,
            tenant_id=context.tenant_id,
            input_payload=arguments,
            metadata={"tool_name": tool_name, "error": str(exc)},
            level="WARNING",
        )
        observe_tool_call(
            context.tenant_id,
            tool_name,
            time.perf_counter() - started_at,
            status="arg_mismatch",
        )
        log.warning("dispatcher_arg_mismatch", tool=tool_name, error=str(exc))
        return ToolResponse.error(f"I had trouble calling {tool_name}. Please try rephrasing.")

    except Exception as exc:
        record_tool_call(context.tenant_id, tool_name)
        get_tracer().record_event(
            "tool_error",
            session_id=context.session_id,
            tenant_id=context.tenant_id,
            input_payload=arguments,
            metadata={"tool_name": tool_name, "error": str(exc)},
            level="ERROR",
        )
        observe_tool_call(
            context.tenant_id,
            tool_name,
            time.perf_counter() - started_at,
            status="error",
        )
        log.error("dispatcher_error", tool=tool_name, error=str(exc), exc_info=True)
        return ToolResponse.error("Something went wrong. Please try again.")




