"""Immutable payload contracts and ordered event selection."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from types import MappingProxyType
from typing import Any, TypeAlias

from ..compose import resolve_json
from ..errors import NotehubError
from ..typing.json import JSONScalar

ContractKey: TypeAlias = tuple[str, str]


class CatalogError(NotehubError):
    """A catalog cannot be loaded or resolved; messages omit payload values."""

    def __init__(self, stage: str, message: str, *, keys: tuple[ContractKey, ...] = ()):
        self.stage = stage
        self.keys = keys
        super().__init__(f"Catalog {stage}: {message}")


def pointer_value(value: object, pointer: str) -> object:
    """Resolve an RFC 6901 JSON Pointer, raising LookupError for missing paths."""
    if pointer and not pointer.startswith("/"):
        raise ValueError("JSON Pointer must be empty or start with /")
    for part in pointer.split("/")[1:]:
        if re.search(r"~(?![01])", part):
            raise ValueError("invalid JSON Pointer escape")
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, Mapping):
            value = value[key]
        elif isinstance(value, (list, tuple)) and re.fullmatch(r"0|[1-9][0-9]*", key):
            value = value[int(key)]
        else:
            raise LookupError("JSON Pointer does not address this value")
    return value


@dataclass(frozen=True, slots=True)
class EventSelector:
    """Match event product/file metadata and an optional exact discriminator."""

    product: str | None = None
    file: str | None = None
    file_glob: str | None = None
    discriminator: str | None = None
    value: JSONScalar = None

    def __post_init__(self) -> None:
        for criterion in (self.product, self.file, self.file_glob):
            if criterion is not None and (not isinstance(criterion, str) or not criterion):
                raise ValueError("selector metadata must be nonempty strings")
        if self.file is not None and self.file_glob is not None:
            raise ValueError("choose file or file_glob")
        if self.discriminator is not None:
            # Validate syntax even when an event does not contain the path.
            if self.discriminator and not self.discriminator.startswith("/"):
                raise ValueError("JSON Pointer must be empty or start with /")
            if re.search(r"~(?![01])", self.discriminator):
                raise ValueError("invalid JSON Pointer escape")
        if not (self.value is None or type(self.value) in (str, int, float, bool)):
            raise TypeError("discriminator value must be a JSON scalar")
        json.dumps(self.value, allow_nan=False)
        if self.discriminator is None and self.value is not None:
            raise ValueError("discriminator value requires a pointer")

    def matches(self, event: Mapping[str, object]) -> bool:
        """Return whether all configured criteria match, including scalar types."""
        if self.product is not None and event.get("product") != self.product:
            return False
        if self.file is not None and event.get("file") != self.file:
            return False
        if self.file_glob is not None:
            filename = event.get("file")
            if not isinstance(filename, str) or not fnmatchcase(filename, self.file_glob):
                return False
        if self.discriminator is not None:
            try:
                actual = pointer_value(event, self.discriminator)
            except LookupError:
                return False
            # JSON numbers compare numerically, but true must not match 1.
            if isinstance(actual, bool) != isinstance(self.value, bool):
                return False
            return actual == self.value
        return True

    def where(self, **changes: object) -> EventSelector:
        """Return a selector with explicitly replaced criteria."""
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class Contract:
    """One stable wire version and its optional portable payload schema."""

    id: str
    version: str
    selector: EventSelector = EventSelector()
    message_ref: str | None = None
    binding: str | None = None
    schema_format: str = "application/schema+json;version=draft-07"
    # Store JSON as text so callers cannot mutate an immutable catalog's schema.
    schema_json: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not isinstance(self.id, str):
            raise ValueError("contract id must be a nonempty string")
        if not self.version or not isinstance(self.version, str):
            raise ValueError("contract version must be a nonempty string")
        if not isinstance(self.selector, EventSelector):
            raise TypeError("contract selector must be an EventSelector")
        for name, value in (("message_ref", self.message_ref), ("binding", self.binding)):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be a nonempty string")
        if self.schema_json is not None:
            schema = json.loads(self.schema_json)
            if not isinstance(schema, (dict, bool)):
                raise ValueError("payload schemas must be objects or booleans")
            json.dumps(schema, allow_nan=False)

    @property
    def key(self) -> ContractKey:
        """Return this contract's stable mapping key."""
        return self.id, self.version

    @property
    def schema(self) -> dict[str, Any] | bool | None:
        """Return a fresh payload schema value, or None when absent."""
        return json.loads(self.schema_json) if self.schema_json is not None else None

    def with_schema(self, schema: Mapping[str, Any] | bool) -> Contract:
        """Attach a copied JSON schema without changing contract identity."""
        return replace(self, schema_json=json.dumps(resolve_json(schema), allow_nan=False))


@dataclass(frozen=True, slots=True, init=False)
class Catalog(Mapping[ContractKey, Contract]):
    """Ordered immutable contracts; later layers replace keys in place."""

    _entries: tuple[Contract, ...]
    _index: Mapping[ContractKey, Contract] = field(compare=False, hash=False, repr=False)

    def __init__(self, contracts: Iterable[Contract] | Mapping[ContractKey, Contract] = ()) -> None:
        values = contracts.values() if isinstance(contracts, Mapping) else contracts
        entries = {contract.key: contract for contract in values}
        if isinstance(contracts, Mapping) and any(
            key != value.key for key, value in contracts.items()
        ):
            raise ValueError("catalog mapping keys must match contract keys")
        object.__setattr__(self, "_entries", tuple(entries.values()))
        object.__setattr__(self, "_index", MappingProxyType(entries))

    def __getitem__(self, key: ContractKey) -> Contract:
        return self._index[key]

    def __iter__(self) -> Iterator[ContractKey]:
        return (entry.key for entry in self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def overlay(self, *catalogs: Catalog) -> Catalog:
        """Layer catalogs in caller order, replacing existing keys in place."""
        return Catalog(entry for layer in (self, *catalogs) for entry in layer.values())

    def add(self, contract: Contract) -> Catalog:
        """Return a catalog containing an additional or replacement contract."""
        return self.overlay(Catalog((contract,)))

    def resolve(self, event: Mapping[str, object]) -> Contract:
        """Select the first matching family, requiring one matching version."""
        matches = [entry for entry in self._entries if entry.selector.matches(event)]
        if not matches:
            raise CatalogError("selection", "no matching contract")
        family = [entry for entry in matches if entry.id == matches[0].id]
        if len(family) != 1:
            raise CatalogError(
                "selection", "ambiguous source versions", keys=tuple(entry.key for entry in family)
            )
        return family[0]
