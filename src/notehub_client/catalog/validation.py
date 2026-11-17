"""Opt-in sample validation. Importing or decoding never invokes validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import NotehubDependencyError
from .loading import ASYNCAPI_FORMAT, JSON_FORMAT
from .models import CatalogError, Contract
from .schema import map_schema


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A failed assertion's locations and keyword, excluding instance values."""

    instance_path: tuple[str | int, ...]
    schema_path: tuple[str | int, ...]
    keyword: str


def validate_sample(contract: Contract, sample: Any) -> tuple[ValidationIssue, ...]:
    """Validate an explicitly supplied sample; return issues without mutating it.

    Supports Draft 07 and the JSON Schema subset of AsyncAPI 3.1 schemas.
    AsyncAPI-specific discriminator semantics are explicitly unsupported.
    """
    try:
        from jsonschema import Draft7Validator
    except ImportError as error:
        raise NotehubDependencyError("sample validation", "validate", "jsonschema") from error
    if contract.schema_json is None:
        raise CatalogError("validation", "contract has no payload schema", keys=(contract.key,))
    if contract.schema_format not in (JSON_FORMAT, ASYNCAPI_FORMAT):
        raise CatalogError("validation", "unsupported schema format", keys=(contract.key,))
    schema = contract.schema
    if schema is None:
        raise CatalogError("validation", "contract has no payload schema", keys=(contract.key,))

    def check(node: dict[str, Any]) -> dict[str, Any]:
        if "discriminator" in node:
            raise ValueError("AsyncAPI discriminator semantics are unsupported")
        if "$schema" in node and node["$schema"] not in (
            "http://json-schema.org/draft-07/schema#",
            "https://json-schema.org/draft-07/schema",
            "https://json-schema.org/draft-07/schema#",
        ):
            raise ValueError("unsupported JSON Schema dialect")
        if "$ref" in node and not node["$ref"].startswith("#"):
            raise ValueError("external schema references are unsupported")
        return node

    try:
        map_schema(schema, check)
        Draft7Validator.check_schema(schema)
        validator = Draft7Validator(schema)
        return tuple(
            ValidationIssue(
                tuple(error.absolute_path), tuple(error.absolute_schema_path), str(error.validator)
            )
            for error in validator.iter_errors(sample)
        )
    except Exception as error:
        raise CatalogError(
            "validation", "invalid or unsupported payload schema", keys=(contract.key,)
        ) from error
