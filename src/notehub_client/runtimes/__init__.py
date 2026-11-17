"""Optional user-facing runtimes for the Notehub client."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .typing import RuntimeModule

# TODO: Are we "hiding" this because it's mutable?
_RUNTIMES: dict[str, str] = {
    "cli": "notehub_client.runtimes.cli",
    "tui": "notehub_client.runtimes.tui",
    "api": "notehub_client.runtimes.api.server",  # TODO: Why is this different than the others?
    "web": "notehub_client.runtimes.web",
    "mcp": "notehub_client.runtimes.mcp",
}


def runtime_names() -> tuple[str, ...]:
    """Return the names accepted by the package runtime dispatcher."""
    return tuple(
        _RUNTIMES
    )  # TODO: Why don't we just freeze and make `_RUNTIMES` be `RUNTIMES` ; if someone then
    #   wants it they can get it.


# TODO: We have so much crazy stuff in here that I don't think we need? Or might be better in helpers?


def _load_runtime(name: str) -> RuntimeModule:
    try:
        module_path = _RUNTIMES[name]
    except KeyError:
        raise ValueError(f"Unknown runtime {name!r}; choose from {', '.join(_RUNTIMES)}.") from None

    module = cast("RuntimeModule", import_module(module_path))
    return module


def run_runtime(name: str, args: Sequence[str] | None = None) -> None:
    """Load and start a runtime."""
    _load_runtime(name).main(args)


__all__ = ["run_runtime", "runtime_names"]
