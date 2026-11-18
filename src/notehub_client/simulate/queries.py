"""Explicit query behavior for the simulated subset of Notehub."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import uuid4

import httpx

from ..compose import resolve_note_body
from .simulation import Simulation

__all__ = ["device_rows", "event_page", "page", "session_page"]

_CURSOR_HISTORY_LIMIT = 4096


def _values(query: httpx.QueryParams, key: str) -> set[str]:
    return {v for item in query.get_list(key) for v in item.split(",")}


def _supported(query: httpx.QueryParams, names: Iterable[str]) -> None:
    unknown = set(query) - set(names)
    if unknown:
        raise NotImplementedError(f"unsupported query keys: {', '.join(sorted(unknown))}")


def _positive(query: httpx.QueryParams, key: str, default: int) -> int:
    value = int(query.get(key, str(default)))
    if value < 1:
        raise ValueError(f"{key} must be positive")
    return value


def page(rows: list[dict[str, Any]], query: httpx.QueryParams, key: str) -> dict[str, Any]:
    """Slice a numbered response page."""
    _supported(query, ("pageSize", "pageNum"))
    size = _positive(query, "pageSize", 100)
    offset = (_positive(query, "pageNum", 1) - 1) * size
    return {key: rows[offset : offset + size], "has_more": offset + size < len(rows)}


def session_page(
    run: Simulation, path: str, rows: list[dict[str, Any]], query: httpx.QueryParams
) -> dict[str, Any]:
    """Page through simulated sync sessions in their creation order."""
    if "cursor" not in query:
        return page(rows, query, "sessions")
    _supported(query, ("cursor", "pageSize", "pageNum"))
    return _cursor_page(run, path, rows, query, "sessions")


def device_rows(
    run: Simulation, project: str, query: httpx.QueryParams, fleet: str | None = None
) -> dict[str, Any]:
    """Return device rows matching supported identity/membership selectors."""
    selectors = {"deviceUID": "uid", "serialNumber": "serial_number", "productUID": "product_uid"}
    _supported(query, (*selectors, "fleetUID", "pageSize", "pageNum"))
    rows = []
    for (pid, _), state in run._states.items():
        definition = state.definition
        if pid != project or (fleet is not None and fleet not in definition.fleet_uids):
            continue
        row = {
            "uid": definition.uid,
            "serial_number": definition.serial_number,
            "best_id": definition.serial_number or definition.uid,
            "product_uid": definition.product_uid,
            "fleet_uids": list(definition.fleet_uids),
            "provisioned": run.scenario.start_time.isoformat(),
            **resolve_note_body(state.readings),
        }
        if state.last_activity is not None:
            row["last_activity"] = state.last_activity
        if any(
            row[field] not in _values(query, key)
            for key, field in selectors.items()
            if key in query
        ):
            continue
        if "fleetUID" in query and not set(definition.fleet_uids) & _values(query, "fleetUID"):
            continue
        rows.append(row)
    return page(
        rows,
        httpx.QueryParams({k: query[k] for k in ("pageSize", "pageNum") if k in query}),
        "devices",
    )


def event_page(
    run: Simulation, path: str, project: str, query: httpx.QueryParams, fleet: str | None = None
) -> dict[str, Any]:
    """Filter and paginate events with opaque cursors scoped to run and query."""
    selectors = {
        "deviceUID": "device",
        "sensorUID": "sensor",
        "sessionUID": "session",
        "eventUID": "event",
        "serialNumber": "sn",
        "files": "file",
    }
    _supported(
        query,
        (
            *selectors,
            "fleetUID",
            "startDate",
            "endDate",
            "dateType",
            "sortBy",
            "sortOrder",
            "systemFilesOnly",
            "selectFields",
            "since",
            "pageSize",
            "pageNum",
            "cursor",
        ),
    )
    rows = [dict(e) for e in run._events if e["app"] == project]
    if "since" in query:
        index = next((i for i, e in enumerate(rows) if e["event"] == query["since"]), None)
        if index is None:
            raise ValueError("unknown since event")
        rows = rows[index + 1 :]
    for key, field in selectors.items():
        if key in query:
            rows = [e for e in rows if e.get(field) in _values(query, key)]
    if fleet is not None:
        rows = [e for e in rows if fleet in run._state(project, e["device"]).definition.fleet_uids]
    fleet_ids = _values(query, "fleetUID") if "fleetUID" in query else set()
    if fleet_ids:
        rows = [
            e
            for e in rows
            if set(run._state(project, e["device"]).definition.fleet_uids) & fleet_ids
        ]
    basis = query.get("dateType", "captured")
    if basis not in ("captured", "uploaded"):
        raise ValueError("dateType must be captured or uploaded")
    date_key = "when" if basis == "captured" else "received"
    for name, lower in (("startDate", True), ("endDate", False)):
        if name in query:
            bound = int(query[name])
            rows = [e for e in rows if (e[date_key] >= bound if lower else e[date_key] <= bound)]
    if "systemFilesOnly" in query:
        flag = query["systemFilesOnly"].lower()
        if flag not in ("true", "false"):
            raise ValueError("systemFilesOnly must be boolean")
        if flag == "true":
            rows = [e for e in rows if e["file"].startswith("_")]
    if "sortBy" in query or "sortOrder" in query:
        fields = {
            "captured": "when",
            "modified": "received",
            "device_uid": "device",
            "best_id": "best_id",
            "device_serial": "sn",
        }
        try:
            sort_key = fields[query.get("sortBy", "captured")]
        except KeyError:
            raise NotImplementedError("unsupported event sort field") from None
        order = query.get("sortOrder", "asc")
        if order not in ("asc", "desc"):
            raise ValueError("sortOrder must be asc or desc")
        rows.sort(key=lambda e: e.get(sort_key, ""), reverse=order == "desc")
    keys = _values(query, "selectFields") if "selectFields" in query else None
    if keys is not None and any("." in key for key in keys):
        raise NotImplementedError("simulation projection supports top-level fields")
    result = _cursor_page(run, path, rows, query, "events")
    if keys is not None:
        result["events"] = [{k: v for k, v in e.items() if k in keys} for e in result["events"]]
    result["through"] = result["next_cursor"]
    return result


def _cursor_page(
    run: Simulation, path: str, rows: list[dict[str, Any]], query: httpx.QueryParams, key: str
) -> dict[str, Any]:
    size = _positive(query, "pageSize", 100)
    signature = (path, tuple(sorted((k, v) for k, v in query.multi_items() if k != "cursor")))
    cursor = query.get("cursor")
    if cursor is not None:
        if "pageNum" in query or "sortBy" in query or "sortOrder" in query:
            raise ValueError("cursor cannot be combined with pageNum or sorting")
        if cursor == "0":
            offset = 0
        else:
            try:
                previous, offset = run._cursors[cursor]
            except KeyError:
                raise ValueError("unknown simulation cursor") from None
            if signature != previous:
                raise ValueError("cursor belongs to another query")
    else:
        offset = (_positive(query, "pageNum", 1) - 1) * size
    selected = rows[offset : offset + size]
    next_cursor = uuid4().hex
    run._cursors[next_cursor] = (signature, offset + len(selected))
    if len(run._cursors) > _CURSOR_HISTORY_LIMIT:
        run._cursors.popitem(last=False)
    return {
        key: selected,
        "has_more": offset + size < len(rows),
        "next_cursor": next_cursor,
    }
