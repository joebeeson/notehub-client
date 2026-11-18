"""Response JSON and envelope validation."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..errors import NotehubResponseError

if TYPE_CHECKING:
    from ..typing import JSONObject, JSONValue

__all__ = [
    "require_collection",
    "require_device_collection",
    "require_json_object",
    "validate_json_value",
]


def _require_uid(obj: JSONObject, context: str) -> None:
    uid = obj.get("uid")
    if not isinstance(uid, str) or not uid:
        raise NotehubResponseError(f"{context} is missing a string uid or the uid is empty")


def require_json_object(
    payload: JSONValue, context: str, *, require_uid: bool = False
) -> JSONObject:
    """Return a JSON object, optionally requiring a nonempty string UID."""
    if not isinstance(payload, dict):
        raise NotehubResponseError(f"Expected a JSON object for {context}")
    if require_uid:
        _require_uid(payload, context)
    return payload


def validate_json_value(payload: object, context: str = "response") -> JSONValue:
    """Validate and return a finite, recursively decoded JSON value.

    Raises ``NotehubResponseError`` for unsupported values, non-string object
    keys, or non-finite floating-point numbers.
    """
    if payload is None or isinstance(payload, (str, bool, int)):
        return payload
    if isinstance(payload, float):
        if not math.isfinite(payload):
            raise NotehubResponseError(f"Expected a finite JSON number in {context}")
        return payload
    if isinstance(payload, list):
        return [validate_json_value(item, context) for item in payload]
    if isinstance(payload, dict):
        if any(not isinstance(key, str) for key in payload):
            raise NotehubResponseError(f"Expected string object keys in {context}")
        return {key: validate_json_value(value, context) for key, value in payload.items()}
    raise NotehubResponseError(f"Expected a JSON value for {context}")


def require_collection(
    payload: JSONValue,
    key: str,
    *,
    paginated: bool = False,
    optional: bool = False,
    require_uid: bool = False,
) -> JSONObject:
    """Validate a response envelope containing a list of JSON objects.

    If ``paginated`` is true, ``has_more`` must be a boolean. A present
    ``next_cursor`` must be a string. If ``optional`` is true, the named list
    may be absent. Set ``require_uid`` for collections whose records must have
    a nonempty string UID. Malformed responses raise ``NotehubResponseError``.
    """
    obj = require_json_object(payload, key)
    if key in obj:
        values = obj[key]
        if not isinstance(values, list):
            raise NotehubResponseError(f"Expected a list of JSON objects for {key}")
        for item in values:
            if not isinstance(item, dict):
                raise NotehubResponseError(f"Expected a list of JSON objects for {key}")
            if require_uid:
                _require_uid(item, f"Record in {key}")
    elif not optional:
        raise NotehubResponseError(f"Missing {key} collection")
    if paginated and type(obj.get("has_more")) is not bool:
        raise NotehubResponseError("Expected boolean has_more in paginated response")
    if "next_cursor" in obj and not isinstance(obj["next_cursor"], str):
        raise NotehubResponseError("Expected a string next_cursor")
    return obj


def require_device_collection(payload: JSONValue, *, paginated: bool = True) -> JSONObject:
    """Validate a device collection, including a nonempty string UID per device."""
    return require_collection(payload, "devices", paginated=paginated, require_uid=True)
