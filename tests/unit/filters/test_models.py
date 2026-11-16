from dataclasses import FrozenInstanceError

import pytest

from notehub_client.filters import DeviceFilters, EventFilters


def test_immutable_query_models_produce_notehub_parameters() -> None:
    filters = EventFilters(
        files=("sensors.qo", "status.qo"),
        device_uids=("dev:one", "dev:two"),
        start_date=100,
        end_date=200,
        date_type="captured",
        system_files_only=False,
    )

    assert dict(filters) == {
        "files": "sensors.qo,status.qo",
        "deviceUID": ("dev:one", "dev:two"),
        "startDate": 100,
        "endDate": 200,
        "dateType": "captured",
        "systemFilesOnly": False,
    }
    with pytest.raises(FrozenInstanceError):
        filters.start_date = 300  # type: ignore[misc]


def test_filter_models_cover_documented_device_and_event_selectors() -> None:
    devices = DeviceFilters(
        notecard_firmware=("notecard-1.2.3",),
        locations=("Chicago",),
        host_firmware=("1.0.0",),
        product_uids=("product:example:project",),
        skus=("KIT-1",),
    )
    events = EventFilters(
        sensor_uids=("sensor:one",),
        serial_numbers=("serial-1",),
        session_uids=("session-1",),
        event_uids=("event-1",),
        sort_by="captured",
        sort_order="desc",
        select_fields="event,device,when,body",
    )

    assert dict(devices) == {
        "notecardFirmware": ("notecard-1.2.3",),
        "location": ("Chicago",),
        "hostFirmware": ("1.0.0",),
        "productUID": ("product:example:project",),
        "sku": ("KIT-1",),
    }
    assert dict(events) == {
        "sensorUID": ("sensor:one",),
        "serialNumber": ("serial-1",),
        "sessionUID": ("session-1",),
        "eventUID": ("event-1",),
        "sortBy": "captured",
        "sortOrder": "desc",
        "selectFields": "event,device,when,body",
    }
