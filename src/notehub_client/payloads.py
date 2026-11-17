"""Explicit typed event decoding and direct upgrades into domain types."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Generic, TypeVar, cast

from cattrs import Converter
from cattrs.errors import AttributeValidationNote, IterableValidationNote

from .catalog import Catalog, CatalogError, Contract, ContractKey
from .errors import NotehubError
from .typing import Event

T = TypeVar("T")


class PayloadDecodeError(NotehubError):
    """A failed selection, structuring, or upgrade, without formatted values."""

    def __init__(
        self, stage: str, *, contract: ContractKey | None = None, paths: tuple[str, ...] = ()
    ) -> None:
        self.stage = stage
        self.contract = contract
        self.paths = paths
        super().__init__(
            f"Payload decode failed during {stage}"
            + (f" for {contract!r}" if contract is not None else "")
        )


def _paths(error: BaseException, path: str = "$") -> tuple[str, ...]:
    for note in getattr(error, "__notes__", ()):
        if isinstance(note, AttributeValidationNote):
            path += f".{note.name}"
        elif isinstance(note, IterableValidationNote):
            path += f"[{note.index!r}]"
    if isinstance(error, BaseExceptionGroup):
        return tuple(
            dict.fromkeys(leaf for child in error.exceptions for leaf in _paths(child, path))
        )
    return (path,)


@dataclass(frozen=True, slots=True)
class DecodedEvent(Generic[T]):
    """A typed body alongside its original, unmodified wire event and contract."""

    raw: Event
    body: T
    contract: Contract


class PayloadDecoder:
    """Snapshot catalog, bindings, direct upgrade functions, and cattrs hooks.

    Prepare converter hooks before construction. Upgrades are keyed by
    ``(source_contract_key, requested_target_type)`` and receive the structured
    source object. Handlers should be pure; callable closure state is not copied.
    """

    def __init__(
        self,
        *,
        catalog: Catalog | None = None,
        bindings: Mapping[str, Any] | None = None,
        upgrades: Mapping[tuple[ContractKey, Any], Callable[[Any], Any]] | None = None,
        converter: Converter | None = None,
    ) -> None:
        self.catalog = catalog if catalog is not None else Catalog()
        self.bindings = MappingProxyType(dict(bindings or {}))
        self.upgrades = MappingProxyType(dict(upgrades or {}))
        self._converter = converter.copy() if converter is not None else Converter()
        for entry in self.catalog.values():
            if entry.binding is not None and entry.binding not in self.bindings:
                raise CatalogError("binding", "unregistered Python binding", keys=(entry.key,))

    def copy(self) -> PayloadDecoder:
        """Create an independent converter with the same immutable configuration."""
        return PayloadDecoder(
            catalog=self.catalog,
            bindings=self.bindings,
            upgrades=self.upgrades,
            converter=self._converter,
        )

    def decode(
        self, event: Event, *, as_type: type[T], contract: ContractKey | None = None
    ) -> DecodedEvent[T]:
        """Decode a selected wire type and optionally apply one direct upgrade."""
        try:
            selected = (
                self.catalog[contract]
                if contract is not None
                else self.catalog.resolve(cast("Mapping[str, object]", event))
            )
        except (CatalogError, KeyError) as error:
            raise PayloadDecodeError("selection", contract=contract) from error
        try:
            body = event["body"]
        except KeyError as error:
            raise PayloadDecodeError("body", contract=selected.key, paths=("$.body",)) from error
        source_type = self.bindings[selected.binding] if selected.binding is not None else as_type
        # Hooks and constructors may mutate their input. Never hand them the raw body.
        try:
            structured = self._converter.structure(deepcopy(body), source_type)
        except Exception as error:
            raise PayloadDecodeError(
                "structure", contract=selected.key, paths=_paths(error)
            ) from error
        if source_type != as_type:
            try:
                upgrade = self.upgrades[(selected.key, as_type)]
            except KeyError as error:
                raise PayloadDecodeError("upgrade_lookup", contract=selected.key) from error
            try:
                structured = upgrade(structured)
                # Generic type forms cannot be checked with isinstance.
                if isinstance(as_type, type) and not isinstance(structured, as_type):
                    raise TypeError("upgrade returned an unexpected type")
            except Exception as error:
                raise PayloadDecodeError("upgrade", contract=selected.key) from error
        return DecodedEvent(event, cast("T", structured), selected)
