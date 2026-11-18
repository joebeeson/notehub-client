"""Pure, normalized export of catalog manifests and companion documents."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from urllib.parse import quote, unquote

from .loading import ASYNCAPI_FORMAT, JSON_FORMAT
from .models import Catalog, CatalogError, Contract, pointer_value
from .schema import map_schema


@dataclass(frozen=True, slots=True)
class CatalogArtifacts:
    """Rendered TOML and named JSON documents, without storage side effects."""

    manifest: str
    documents: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "documents", MappingProxyType(dict(self.documents)))


def _scalar(value: object) -> str:
    # JSON scalar syntax overlaps TOML except null and raw DEL. Keep Unicode
    # literal: JSON's surrogate-pair escapes are not legal TOML scalar escapes.
    rendered = json.dumps(value, ensure_ascii=False, allow_nan=False).replace("\x7f", "\\u007f")
    rendered.encode("utf-8")
    return rendered


def _payload(contract: Contract, name: str) -> dict[str, Any]:
    schema = contract.schema
    if schema is None:
        raise ValueError("missing schema")
    if contract.schema_format not in (JSON_FORMAT, ASYNCAPI_FORMAT):
        raise ValueError("unsupported schema format")
    root = f"/components/messages/{name}/payload/schema"

    def relocate(node: dict[str, Any]) -> dict[str, Any]:
        if "$id" in node:
            raise ValueError("schema resource scopes are unsupported")
        if "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#"):
                raise ValueError("external schema reference")
            pointer = unquote(ref[1:], errors="strict")
            target = pointer_value(schema, pointer)
            if not isinstance(target, (dict, bool)):
                raise ValueError("reference does not identify a schema")
            node["$ref"] = "#" + quote(root + pointer, safe="/~")
        return node

    return {"schemaFormat": contract.schema_format, "schema": map_schema(schema, relocate)}


def export_artifacts(catalog: Catalog) -> CatalogArtifacts:
    """Render a self-contained catalog without reading or writing artifacts.

    Contract order, selectors, bindings and schema formats are preserved. Source
    document layout and message references are replaced with generated locations.
    Contracts need attached schemas using a supported format and local JSON
    Pointer references, without resource scopes. Failures identify the contract
    key without formatting schema values.
    """
    manifest = ["catalog_version = 1"]
    messages = {}
    for index, contract in enumerate(catalog.values()):
        name = f"contract{index}"
        try:
            messages[name] = {"payload": _payload(contract, name)}
            manifest.extend(
                [
                    "",
                    "[[contracts]]",
                    f"id = {_scalar(contract.id)}",
                    f"version = {_scalar(contract.version)}",
                    f'message_ref = "messages.json#/components/messages/{name}"',
                ]
            )
            if contract.binding is not None:
                manifest.append(f"binding = {_scalar(contract.binding)}")
            selector = contract.selector
            criteria = {
                "product": selector.product,
                "file": selector.file,
                "file_glob": selector.file_glob,
                "discriminator": selector.discriminator,
                "value": selector.value,
            }
            present = {key: value for key, value in criteria.items() if value is not None}
            if present:
                manifest.append("[contracts.selector]")
                manifest.extend(f"{key} = {_scalar(value)}" for key, value in present.items())
            # Validate Unicode now, while errors can still name their contract.
            json.dumps(messages[name], ensure_ascii=False, allow_nan=False).encode("utf-8")
        except Exception as error:
            raise CatalogError(
                "export",
                "contract cannot be represented by the portable profile",
                keys=(contract.key,),
            ) from error
    documents = {}
    if messages:
        document = {
            "asyncapi": "3.1.0",
            "info": {"title": "Exported payload catalog", "version": "1"},
            "components": {"messages": messages},
        }
        documents["messages.json"] = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    return CatalogArtifacts("\n".join(manifest) + "\n", documents)


__all__ = ["CatalogArtifacts", "export_artifacts"]
