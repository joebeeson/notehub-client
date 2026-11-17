"""Low-noise MCP request timing without logging arguments or returned data."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import mcp.types as mt

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

_LOGGER = logging.getLogger("notehub_client.runtimes.mcp")


class MCPDiagnosticsMiddleware(Middleware):
    """Log MCP tool and resource duration, without exposing their contents."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        """Time one tool invocation and report failure type without payloads."""
        started = time.perf_counter()
        name = context.message.name
        try:
            result = await call_next(context)
        except Exception as error:
            _LOGGER.warning(
                "MCP tool failed name=%s duration_ms=%.1f error_type=%s",
                name,
                (time.perf_counter() - started) * 1000,
                type(error).__name__,
            )
            raise
        _LOGGER.info(
            "MCP tool completed name=%s duration_ms=%.1f",
            name,
            (time.perf_counter() - started) * 1000,
        )
        return result

    async def on_read_resource(
        self,
        context: MiddlewareContext[mt.ReadResourceRequestParams],
        call_next: CallNext[mt.ReadResourceRequestParams, Any],
    ) -> Any:
        """Time one resource read without logging its potentially identifying URI."""
        started = time.perf_counter()
        try:
            result = await call_next(context)
        except Exception as error:
            _LOGGER.warning(
                "MCP resource read failed duration_ms=%.1f error_type=%s",
                (time.perf_counter() - started) * 1000,
                type(error).__name__,
            )
            raise
        _LOGGER.info(
            "MCP resource read completed duration_ms=%.1f",
            (time.perf_counter() - started) * 1000,
        )
        return result


def configure_mcp_logging(level: str = "WARNING") -> None:
    """Configure standard logging to stderr for the stdio MCP process."""
    log_level = logging.getLevelNamesMapping().get(level.upper())
    if not isinstance(log_level, int):
        raise ValueError(f"unknown logging level: {level}")
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(log_level)
    else:
        logging.basicConfig(level=log_level, format="%(levelname)s %(name)s: %(message)s")


__all__ = ["MCPDiagnosticsMiddleware", "configure_mcp_logging"]
