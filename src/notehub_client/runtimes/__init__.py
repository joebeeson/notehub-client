"""Optional user-facing runtimes for the Notehub client."""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from typing import Protocol, cast

from ..errors import NotehubDependencyError

_RUNTIMES: dict[str, tuple[str, frozenset[str]]] = {
    "cli": ("notehub_client.runtimes.cli", frozenset({"click", "rich"})),
    "tui": ("notehub_client.runtimes.tui", frozenset({"textual", "click", "rich"})),
}


class _RuntimeModule(Protocol):
    def main(self, args: Sequence[str] | None = None) -> None: ...


def runtime_names() -> tuple[str, ...]:
    """Return the names accepted by the package runtime dispatcher."""
    return tuple(_RUNTIMES)


def _load_runtime(name: str) -> tuple[_RuntimeModule, str]:
    try:
        module_path, optional_modules = _RUNTIMES[name]
    except KeyError:
        raise ValueError(f"Unknown runtime {name!r}; choose from {', '.join(_RUNTIMES)}.") from None

    try:
        module = cast(_RuntimeModule, import_module(module_path))
        return module, name
    except ModuleNotFoundError as error:
        missing_root = (error.name or "").partition(".")[0]
        if missing_root not in optional_modules:
            raise
        raise NotehubDependencyError(f"{name} runtime", name, missing_root) from error


def run_runtime(name: str, args: Sequence[str] | None = None) -> None:
    """Load and start a runtime, translating only its known optional imports."""
    module, runtime = _load_runtime(name)
    try:
        module.main(args)
    except ModuleNotFoundError as error:
        missing_root = (error.name or "").partition(".")[0]
        optional_modules = _RUNTIMES[runtime][1]
        if missing_root not in optional_modules:
            raise
        raise NotehubDependencyError(f"{runtime} runtime", runtime, missing_root) from error


__all__ = ["run_runtime", "runtime_names"]
