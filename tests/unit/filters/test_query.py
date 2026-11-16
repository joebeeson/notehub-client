from collections.abc import Callable

import pytest

from notehub_client.filters import (
    Query,
    QueryFilter,
    combine,
    date_range,
    devices,
    events,
    files,
    fleets,
    merge_query_params,
    sensors,
    serial_numbers,
    sessions,
)


def test_query_factories_compose_as_immutable_mappings() -> None:
    query = combine(devices("dev:one"), files("sensors.qo")).date_range(start=10, end=20)
    assert isinstance(query, Query)
    assert isinstance(query, QueryFilter)
    assert dict(query) == {
        "deviceUID": ("dev:one",),
        "files": "sensors.qo",
        "startDate": 10,
        "endDate": 20,
    }
    assert query.devices("dev:two")["deviceUID"] == ("dev:one", "dev:two")
    assert query["deviceUID"] == ("dev:one",)
    assert query.to_query_params() is not query.to_query_params()
    assert len(query) == 4


def test_query_composition_rejects_duplicate_wire_keys() -> None:
    with pytest.raises(ValueError, match="specified twice"):
        combine(devices("dev:one"), {"deviceUID": ("dev:two",)})
    with pytest.raises(ValueError, match="specified twice"):
        merge_query_params(devices("dev:one"), {"deviceUID": ("dev:two",)})


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        pytest.param(devices("dev:one"), {"deviceUID": ("dev:one",)}, id="devices"),
        pytest.param(sensors("sensor:one"), {"sensorUID": ("sensor:one",)}, id="sensors"),
        pytest.param(fleets("fleet:one"), {"fleetUID": ("fleet:one",)}, id="fleets"),
        pytest.param(
            serial_numbers("serial:one"),
            {"serialNumber": ("serial:one",)},
            id="serial-numbers",
        ),
        pytest.param(sessions("session:one"), {"sessionUID": ("session:one",)}, id="sessions"),
        pytest.param(events("event:one"), {"eventUID": ("event:one",)}, id="events"),
        pytest.param(date_range(start=10, end=20), {"startDate": 10, "endDate": 20}, id="dates"),
    ],
)
def test_query_selector_factories_return_wire_parameter_mappings(
    query: Query, expected: dict[str, object]
) -> None:
    assert dict(query) == expected


def test_query_event_options_compose_fluently() -> None:
    query = (
        Query()
        .date_type("captured")
        .sort_by("captured")
        .sort_order("desc")
        .system_files_only()
        .select_fields("event,when,body")
        .since("2026-01-01T00:00:00Z")
    )
    assert dict(query) == {
        "dateType": "captured",
        "sortBy": "captured",
        "sortOrder": "desc",
        "systemFilesOnly": True,
        "selectFields": "event,when,body",
        "since": "2026-01-01T00:00:00Z",
    }


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        pytest.param(lambda: Query().devices(""), "selector values", id="empty-device"),
        pytest.param(lambda: Query().files(""), "file names", id="empty-file"),
        pytest.param(
            lambda: Query().system_files_only(1),  # type: ignore[arg-type]
            "boolean",
            id="non-boolean-option",
        ),
        pytest.param(lambda: Query().select_fields(""), "nonempty", id="empty-select-fields"),
        pytest.param(lambda: Query().since(""), "nonempty", id="empty-since"),
    ],
)
def test_query_builders_reject_invalid_values(factory: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_empty_selector_is_a_no_op_and_files_append() -> None:
    query = files("sensors.qo")
    assert query.devices() is query
    assert dict(query.files("status.qo")) == {"files": "sensors.qo,status.qo"}


def test_query_from_value_normalizes_list_values() -> None:
    query = Query.from_value({"deviceUID": ["dev:one", "dev:two"]})  # type: ignore[arg-type]
    assert query["deviceUID"] == ("dev:one", "dev:two")


@pytest.mark.parametrize(
    ("factory", "error_type", "message"),
    [
        pytest.param(
            lambda: Query.from_value({"": "value"}),
            ValueError,
            "nonempty strings",
            id="empty-key",
        ),
        pytest.param(
            lambda: Query.from_value({1: "value"}),  # type: ignore[dict-item]
            ValueError,
            "nonempty strings",
            id="non-string-key",
        ),
        pytest.param(
            lambda: Query.from_value({"deviceUID": ("dev:one", 2)}),  # type: ignore[arg-type]
            ValueError,
            "repeated query values must be strings",
            id="non-string-repeated-value",
        ),
        pytest.param(
            lambda: Query.from_value({"reading": float("inf")}),
            ValueError,
            "query numbers must be finite",
            id="non-finite-number",
        ),
        pytest.param(
            lambda: Query.from_value({"custom": object()}),  # type: ignore[dict-item]
            ValueError,
            "query values must be",
            id="unsupported-value",
        ),
        pytest.param(
            lambda: Query(_items=(("deviceUID", "dev:one"), ("deviceUID", "dev:two"))),
            ValueError,
            "query keys cannot be repeated",
            id="duplicate-wire-key",
        ),
        pytest.param(
            lambda: Query.from_value(object()),  # type: ignore[arg-type]
            TypeError,
            "mappings or implement to_query_params",
            id="unsupported-query-source",
        ),
    ],
)
def test_query_source_validation(
    factory: Callable[[], object], error_type: type[Exception], message: str
) -> None:
    with pytest.raises(error_type, match=message):
        factory()
