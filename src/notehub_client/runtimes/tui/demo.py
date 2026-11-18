"""Deterministic local data for the credential-free terminal workbench."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ...errors import NotehubAuthenticationError, NotehubPermissionError, NotehubTransportError
from ...filters import Query
from .service import (
    COLLECTION_KEYS,
    OPERATIONS,
    PAGE_SIZE,
    PROJECT_OPERATIONS,
    UID_OPERATIONS,
    adapt_page,
)
from .state import PageResult

DEMO_PROJECT_UID = "app:demo-orchard"
EMPTY_PROJECT_UID = "app:demo-empty"
DEMO_DEVICE_UID = "dev:demo-west"
DEMO_FLEET_UID = "fleet:demo-sensors"


def demo_events() -> list[dict[str, Any]]:
    """Build independent synthetic event records, including wire-shape edge cases."""
    rows: list[dict[str, Any]] = []
    for i in range(137):
        rows.append(
            {
                "event": f"ev:demo-{i:04d}",
                "device": DEMO_DEVICE_UID if i % 3 else "dev:demo-east",
                "file": "sensors.qo" if i % 4 else "health.qo",
                "when": 1794916800 - i * 60,
                "received": 1794916802 - i * 60,
                "body": {
                    "temperature": round(18 + (i % 12) * 0.4, 1),
                    "humidity": 45 + i % 10,
                    "location": {"zone": "west"},
                    "label": "[bold]literal[/bold]",
                },
                "sensor": "sensor:demo-temperature",
                "session": "session:demo-1",
            }
        )
    rows[2].pop("event")
    rows[3]["event"] = rows[1]["event"]
    rows[4]["body"] = None
    rows[5]["body"] = {}
    rows[6].pop("body")
    rows[7].pop("when")
    rows[8]["body"] = {"message": "Orchard café — 温度", "nested": [1, None, {"ok": True}]}
    rows[9]["body"] = {"message": "x" * 70000, "children": list(range(250))}
    return rows


def _selector_values(value: object) -> tuple[str, ...]:
    """Normalize a selector query value while rejecting non-string wire values."""
    if isinstance(value, str):
        return tuple(value.split(","))
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise ValueError("Demo selector filters must contain strings")


def _matches_selector(record: dict[str, Any], field: str, choices: tuple[str, ...]) -> bool:
    value = record.get(field)
    return isinstance(value, str) and value in choices


def _matches_date(value: object, boundary: float, *, lower: bool) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return value >= boundary if lower else value <= boundary


class DemoReadService:
    """Offer the same read seam as TUIReadService without constructing HTTP clients."""

    def __init__(self) -> None:
        self._events = demo_events()
        self._failures: dict[str, Exception] = {}
        self.reads: list[str] = []

    def fail_next(self, operation: str, error: Exception) -> None:
        """Inject one failure for deterministic demonstrations and recovery tests."""
        self._failures[operation] = error

    async def read(
        self,
        operation: str,
        *,
        project_uid: str | None = None,
        uid: str | None = None,
        query: Query | None = None,
        cursor: str = "0",
        page_num: int = 1,
    ) -> PageResult:
        """Return synthetic records; never access environment credentials or network."""
        if operation not in OPERATIONS:
            raise ValueError("Unknown read operation")
        if operation in PROJECT_OPERATIONS and not project_uid:
            raise ValueError("Select a project first")
        if operation in UID_OPERATIONS and not uid:
            raise ValueError("Select a record first")
        self.reads.append(operation)
        error = self._failures.pop(operation, None)
        if error is not None:
            raise error
        if project_uid == "app:demo-denied":
            raise NotehubPermissionError(403, "Demo permission denied")
        if project_uid == "app:demo-auth":
            raise NotehubAuthenticationError(401, "Demo authentication rejected")
        if project_uid == "app:demo-offline":
            raise NotehubTransportError("Demo transport unavailable")
        if type(page_num) is not int or page_num < 1:
            raise ValueError("page_num must be positive")
        if not cursor.isdecimal():
            raise ValueError("Invalid demo cursor")
        records = self._records(operation, uid)
        if (
            project_uid == EMPTY_PROJECT_UID
            and operation in PROJECT_OPERATIONS
            and operation != "project"
        ):
            records = []
        if operation == "project":
            records = [
                {
                    "uid": project_uid,
                    "label": "Empty demonstration"
                    if project_uid == EMPTY_PROJECT_UID
                    else "Orchard demonstration",
                }
            ]
        params = (query or Query()).to_query_params()
        if operation in {"events", "fleet_events", "latest"}:
            if (
                operation in {"events", "fleet_events"}
                and {"pageNum", "sortBy", "sortOrder", "cursor", "pageSize"} & params.keys()
            ):
                raise ValueError("Pagination and sorting keys are not event filters")
            for key, field in {
                "deviceUID": "device",
                "files": "file",
                "sensorUID": "sensor",
                "sessionUID": "session",
                "eventUID": "event",
                "serialNumber": "sn",
            }.items():
                expected = params.get(key)
                if expected is not None:
                    choices = _selector_values(expected)
                    records = [row for row in records if _matches_selector(row, field, choices)]
            fleet_filter = params.get("fleetUID")
            if fleet_filter is not None:
                choices = _selector_values(fleet_filter)
                if DEMO_FLEET_UID not in choices:
                    records = []
            date_field = "received" if params.get("dateType") == "uploaded" else "when"
            for key, lower in (("startDate", True), ("endDate", False)):
                raw_boundary = params.get(key)
                if raw_boundary is not None:
                    if not isinstance(raw_boundary, (str, int, float)) or isinstance(
                        raw_boundary, bool
                    ):
                        raise ValueError("Demo date filters must be numeric timestamps")
                    boundary = float(raw_boundary)
                    records = [
                        row
                        for row in records
                        if _matches_date(row.get(date_field), boundary, lower=lower)
                    ]
            if params.get("systemFilesOnly"):
                records = [row for row in records if str(row.get("file", "")).startswith("_")]
        if operation in {"events", "fleet_events"}:
            start = int(cursor)
            page_rows = records[start : start + PAGE_SIZE]
            has_more = start + PAGE_SIZE < len(records)
            event_payload: dict[str, Any] = {"events": page_rows, "has_more": has_more}
            if has_more:
                event_payload["next_cursor"] = str(start + PAGE_SIZE)
            payload: object = event_payload
        elif operation in {"projects", "devices", "fleet_devices", "sessions"}:
            start = (page_num - 1) * PAGE_SIZE
            payload = {
                COLLECTION_KEYS[operation]: records[start : start + PAGE_SIZE],
                "has_more": start + PAGE_SIZE < len(records),
            }
        elif operation == "environment":
            # Synthetic sensitive-field data exercises masking; it cannot authenticate.
            payload = {
                "environment_variables": {
                    "PUMP_TOKEN": "never displayed",  # nosec B105
                    "INTERVAL": "60",
                }
            }
        elif operation in COLLECTION_KEYS:
            payload = {COLLECTION_KEYS[operation]: records}
        elif operation in {"routes", "monitors"}:
            payload = records
        else:
            payload = records[0] if records else {}
        return adapt_page(operation, deepcopy(payload), cursor=cursor, page_num=page_num)

    def _records(self, operation: str, uid: str | None) -> list[dict[str, Any]]:
        devices = [
            {
                "uid": DEMO_DEVICE_UID,
                "serial_number": "Orchard west",
                "fleet_uids": [DEMO_FLEET_UID],
                "voltage": 3.8,
                "temperature": 21.2,
                "last_activity": "2026-11-17T12:00:00Z",
            },
            {
                "uid": "dev:demo-east",
                "serial_number": "Orchard east",
                "fleet_uids": [DEMO_FLEET_UID],
                "last_activity": "2026-11-17T11:58:00Z",
            },
        ]
        if operation == "projects":
            return [
                {"uid": DEMO_PROJECT_UID, "label": "Orchard demonstration"},
                {"uid": EMPTY_PROJECT_UID, "label": "Empty demonstration"},
            ]
        if operation in {"devices", "fleet_devices"}:
            return devices
        if operation == "device":
            return [row for row in devices if row["uid"] == uid]
        if operation in {"events", "fleet_events"}:
            return self._events
        if operation == "latest":
            return [row for row in self._events if row.get("device") == uid][:4]
        if operation == "sessions":
            return [
                {
                    "session": "session:demo-1",
                    "device": uid,
                    "session_began": 1794916800,
                    "period": {"duration": 12},
                }
            ]
        if operation == "fleets":
            return [{"uid": DEMO_FLEET_UID, "label": "Orchard sensors"}]
        if operation == "routes":
            return [
                {
                    "uid": "route:demo-archive",
                    "label": "Synthetic archive",
                    "type": "http",
                    "disabled": False,
                }
            ]
        if operation == "jobs":
            return [{"uid": "job:demo-1", "status": "completed", "label": "Synthetic export"}]
        if operation == "monitors":
            return [
                {
                    "uid": "monitor:demo-1",
                    "label": "Synthetic inactivity monitor",
                    "disabled": False,
                }
            ]
        if operation == "usage":
            return [{"date": "2026-11-17", "count": 123, "label": "Synthetic API usage"}]
        if operation in {"organizations", "organization"}:
            return [{"uid": uid or "org:demo", "label": "Demo organization", "balance": 5000}]
        if operation in {"billing_accounts", "billing_account"}:
            return [{"uid": uid or "billing:demo", "label": "Demo billing", "balance": 5000}]
        if operation in {"organization_history", "billing_history"}:
            return [{"uid": "history:demo", "when": "2026-11-17", "balance": 5000}]
        return []


__all__ = [
    "DEMO_DEVICE_UID",
    "DEMO_FLEET_UID",
    "DEMO_PROJECT_UID",
    "EMPTY_PROJECT_UID",
    "DemoReadService",
    "demo_events",
]
