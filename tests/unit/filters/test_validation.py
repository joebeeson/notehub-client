from collections.abc import Callable

import pytest

from notehub_client.filters import BalanceHistoryFilters, DeviceFilters, EventFilters


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        pytest.param(lambda: EventFilters(start_date=2, end_date=1), "no later", id="date-order"),
        pytest.param(
            lambda: EventFilters(date_type="updated"),  # type: ignore[arg-type]
            "date_type",
            id="unsupported-date-type",
        ),
        pytest.param(
            lambda: EventFilters(sort_by="when"),  # type: ignore[arg-type]
            "sort_by",
            id="unsupported-sort-field",
        ),
    ],
)
def test_event_filter_validation(factory: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        pytest.param(
            lambda: EventFilters(files="sensors.qo"),
            "sequence of nonempty strings",
            id="string-instead-of-sequence",
        ),
        pytest.param(
            lambda: EventFilters(system_files_only=1),  # type: ignore[arg-type]
            "system_files_only",
            id="non-boolean-system-files-option",
        ),
        pytest.param(lambda: EventFilters(select_fields=""), "select_fields", id="empty-fields"),
        pytest.param(lambda: EventFilters(since=""), "since", id="empty-since"),
    ],
)
def test_event_filter_rejects_invalid_optional_fields(
    factory: Callable[[], object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_device_filter_validation() -> None:
    with pytest.raises(ValueError, match="only nonempty strings"):
        DeviceFilters(device_uids=("",))


def test_event_filter_normalizes_list_values_to_tuples() -> None:
    filters = EventFilters(files=["sensors.qo"])
    assert filters.files == ("sensors.qo",)


def test_balance_history_filter_validates_unix_timestamp_window() -> None:
    assert dict(BalanceHistoryFilters(start_date=10, end_date=20)) == {
        "startDate": 10,
        "endDate": 20,
    }
    with pytest.raises(ValueError, match="no later"):
        BalanceHistoryFilters(start_date=20, end_date=10)
    with pytest.raises(ValueError, match="nonnegative integer"):
        BalanceHistoryFilters(start_date=True)
