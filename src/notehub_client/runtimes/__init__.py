"""Optional user-facing runtimes for the Notehub client."""

from __future__ import annotations

from importlib import import_module
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .typing import RuntimeModule

# Public metadata is safe to inspect without importing optional runtime packages.
# The API package owns the shared ASGI app; its server module owns CLI startup.
RUNTIMES: Mapping[str, str] = MappingProxyType(
    {
        "cli": "notehub_client.runtimes.cli",
        "tui": "notehub_client.runtimes.tui",
        "api": "notehub_client.runtimes.api.server",
        "web": "notehub_client.runtimes.web",
        "mcp": "notehub_client.runtimes.mcp",
    }
)


def runtime_names() -> tuple[str, ...]:
    """Return the names accepted by the package runtime dispatcher."""
    return tuple(RUNTIMES)


def _load_runtime(name: str) -> RuntimeModule:
    try:
        module_path = RUNTIMES[name]
    except KeyError:
        raise ValueError(f"Unknown runtime {name!r}; choose from {', '.join(RUNTIMES)}.") from None

    module = cast("RuntimeModule", import_module(module_path))
    return module


def run_runtime(name: str, args: Sequence[str] | None = None) -> None:
    """Load and start a runtime."""
    _load_runtime(name).main(args)


__all__ = ["RUNTIMES", "run_runtime", "runtime_names"]
