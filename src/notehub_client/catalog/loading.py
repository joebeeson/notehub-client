"""Explicit TOML/AsyncAPI artifact loading without executable Python metadata."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import unquote, urldefrag

from ..compose import resolve_json
from ..errors import NotehubDependencyError
from .models import Catalog, CatalogError, Contract, EventSelector, pointer_value
from .schema import map_schema

Reader = Callable[[str], str]
JSON_FORMAT = "application/schema+json;version=draft-07"
ASYNCAPI_FORMAT = "application/vnd.aai.asyncapi+json;version=3.1.0"


def _document(text: str, name: str) -> dict[str, Any]:
    if name.lower().endswith((".yaml", ".yml")):
        try:
            import yaml
        except ImportError as error:
            raise NotehubDependencyError("YAML catalogs", "yaml", "yaml") from error
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    # Enforce the JSON data model even for YAML (timestamps, sets, etc. are invalid).
    data = resolve_json(data)
    if not isinstance(data, dict):
        raise ValueError("AsyncAPI document must be an object")
    if data.get("asyncapi") != "3.1.0":
        raise ValueError("only AsyncAPI 3.1.0 documents are supported")
    return data


def _reference(document: object, ref: str) -> Any:
    if not ref.startswith("#"):
        raise ValueError("only in-document AsyncAPI references are supported")
    return pointer_value(document, unquote(ref[1:]))


def _object(document: object, value: Any) -> Any:
    seen: set[str] = set()
    while isinstance(value, dict) and "$ref" in value:
        ref = value["$ref"]
        if ref in seen:
            raise ValueError("cyclic AsyncAPI object reference")
        seen.add(ref)
        value = _reference(document, ref)
    return value


def _schema(document: object, schema: Any) -> Any:
    """Bundle document-relative schema references, preserving recursive schemas."""
    definitions: dict[str, Any] = {}
    names: dict[str, str] = {}

    def transform(node: dict[str, Any]) -> dict[str, Any]:
        # References in this profile are relative to the AsyncAPI document.
        # Remove resource scopes when bundling into a standalone schema.
        node.pop("$id", None)
        if "$ref" in node:
            ref = node["$ref"]
            if ref not in names:
                name = f"ref{len(names)}"
                names[ref] = name
                definitions[name] = map_schema(_reference(document, ref), transform)
            node["$ref"] = f"#/definitions/{names[ref]}"
        return node

    result = map_schema(schema, transform)
    if definitions:
        return {"allOf": [result], "definitions": definitions}
    return result


def loads(text: str, *, read_document: Reader) -> Catalog:
    """Load a TOML catalog, obtaining named AsyncAPI documents through a reader.

    ``read_document`` receives the artifact name exactly as written in TOML.
    It is invoked only while loading; decoding never performs artifact I/O.
    """
    try:
        data = tomllib.loads(text)
        if data.get("catalog_version") != 1:
            raise ValueError("catalog_version must be 1")
        documents: dict[str, dict[str, Any]] = {}
        entries = []
        for item in data.get("contracts", []):
            filename, fragment = urldefrag(item["message_ref"])
            if not filename or not fragment:
                raise ValueError("message_ref requires a document and fragment")
            if filename not in documents:
                documents[filename] = _document(read_document(filename), filename)
            document = documents[filename]
            message = _object(document, _reference(document, f"#{fragment}"))
            schema = _object(document, message["payload"])
            schema_format = ASYNCAPI_FORMAT
            if isinstance(schema, dict) and "schemaFormat" in schema:
                schema_format = schema["schemaFormat"]
                schema = schema["schema"]
            if schema_format not in (JSON_FORMAT, ASYNCAPI_FORMAT):
                raise ValueError("unsupported payload schema format")
            selector = EventSelector(**item.get("selector", {}))
            entries.append(
                Contract(
                    id=item["id"],
                    version=item["version"],
                    selector=selector,
                    message_ref=item["message_ref"],
                    binding=item.get("binding"),
                    schema_format=schema_format,
                ).with_schema(_schema(document, schema))
            )
        return Catalog(entries)
    except (NotehubDependencyError, CatalogError):
        raise
    except Exception as error:
        raise CatalogError("load", "invalid catalog or unsupported AsyncAPI artifact") from error


def load(source: str | Path | TextIO, *, read_document: Reader | None = None) -> Catalog:
    """Load local TOML; resolve document paths relative to its containing folder.

    Streams require an explicit reader to define their reference location.
    """
    try:
        if isinstance(source, (str, Path)):
            path = Path(source)
            text = path.read_text(encoding="utf-8")
            reader = read_document or (
                lambda name: (path.parent / name).read_text(encoding="utf-8")
            )
        else:
            text = source.read()
            if read_document is None:
                raise ValueError("stream loading requires read_document")
            reader = read_document
        return loads(text, read_document=reader)
    except (CatalogError, NotehubDependencyError):
        raise
    except Exception as error:
        raise CatalogError("load", "cannot read catalog artifacts") from error
