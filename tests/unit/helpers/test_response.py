import pytest

from notehub_client.errors import NotehubResponseError
from notehub_client.helpers import (
    require_collection,
    require_device_collection,
    require_json_object,
    validate_json_value,
)
from notehub_client.typing import JSONValue


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(None, None, id="null"),
        pytest.param(
            {"events": [{"when": 10, "body": [True, None]}]},
            {"events": [{"when": 10, "body": [True, None]}]},
            id="nested-json",
        ),
    ],
)
def test_validate_json_value_accepts_json_values(payload: JSONValue, expected: JSONValue) -> None:
    assert validate_json_value(payload) == expected


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        pytest.param(float("nan"), "finite JSON number", id="non-finite-number"),
        pytest.param({1: "value"}, "string object keys", id="non-string-object-key"),
        pytest.param(object(), "JSON value", id="unsupported-object"),
    ],
)
def test_validate_json_value_rejects_non_json_values(payload: object, message: str) -> None:
    with pytest.raises(NotehubResponseError, match=message):
        validate_json_value(payload)


def test_validate_json_value_includes_context_for_nested_invalid_values() -> None:
    with pytest.raises(NotehubResponseError, match="event response"):
        validate_json_value({"reading": float("inf")}, "event response")


def test_require_json_object_returns_objects_and_rejects_other_values() -> None:
    payload: JSONValue = {"uid": "dev:one"}
    assert require_json_object(payload, "device") is payload

    with pytest.raises(NotehubResponseError, match="JSON object"):
        require_json_object([], "device")


@pytest.mark.parametrize(
    ("payload", "key", "paginated", "optional", "message"),
    [
        pytest.param([], "events", False, False, "JSON object", id="not-an-object"),
        pytest.param({}, "events", False, False, "Missing events", id="missing-required"),
        pytest.param(
            {"events": "not-a-list"},
            "events",
            False,
            False,
            "list of JSON objects",
            id="not-a-list",
        ),
        pytest.param(
            {"events": [None]}, "events", False, False, "list of JSON objects", id="non-object-item"
        ),
        pytest.param(
            {"events": [], "has_more": "yes"},
            "events",
            True,
            False,
            "boolean has_more",
            id="invalid-has-more",
        ),
        pytest.param(
            {"events": [], "next_cursor": 1},
            "events",
            False,
            False,
            "string next_cursor",
            id="invalid-next-cursor",
        ),
    ],
)
def test_require_collection_rejects_malformed_envelopes(
    payload: JSONValue, key: str, paginated: bool, optional: bool, message: str
) -> None:
    with pytest.raises(NotehubResponseError, match=message):
        require_collection(payload, key, paginated=paginated, optional=optional)


def test_require_collection_allows_an_absent_optional_list() -> None:
    assert require_collection({}, "events", optional=True) == {}


@pytest.mark.parametrize(
    ("payload", "is_valid"),
    [
        pytest.param({"devices": [{"uid": "dev:one"}], "has_more": False}, True, id="valid"),
        pytest.param(
            {"devices": [{"name": "missing-uid"}], "has_more": False},
            False,
            id="missing-uid",
        ),
        pytest.param({"devices": [{"uid": 1}], "has_more": False}, False, id="non-string-uid"),
    ],
)
def test_require_device_collection_checks_device_uids(payload: JSONValue, is_valid: bool) -> None:
    if is_valid:
        assert require_device_collection(payload) == payload
    else:
        with pytest.raises(NotehubResponseError, match="string uid"):
            require_device_collection(payload)
