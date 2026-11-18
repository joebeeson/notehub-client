"""Bounded read adapters for terminal workspaces, independent of Textual."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from copy import deepcopy
from typing import Any, AsyncContextManager, Protocol

from ...client import NotehubClient
from ...errors import NotehubResponseError
from ...filters import BalanceHistoryFilters, CursorPagination, Pagination, Query
from ...observe import operation_context
from ...simulate import Simulation
from ...typing.observe import Observer
from .state import PageResult

PAGE_SIZE = 50
COLLECTION_KEYS = {
    "projects": "projects",
    "events": "events",
    "devices": "devices",
    "latest": "latest_events",
    "sessions": "sessions",
    "fleets": "fleets",
    "fleet_devices": "devices",
    "fleet_events": "events",
    "jobs": "jobs",
    "usage": "data",
    "organizations": "organizations",
    "organization_history": "data",
    "billing_accounts": "billing_accounts",
    "billing_history": "data",
}
PROJECT_OPERATIONS = frozenset(
    {
        "project",
        "events",
        "devices",
        "device",
        "latest",
        "sessions",
        "environment",
        "fleets",
        "fleet_devices",
        "fleet_events",
        "routes",
        "jobs",
        "monitors",
        "usage",
    }
)
UID_OPERATIONS = frozenset(
    {
        "device",
        "latest",
        "sessions",
        "environment",
        "fleet_devices",
        "fleet_events",
        "organization",
        "organization_history",
        "billing_account",
        "billing_history",
    }
)
OPERATIONS = PROJECT_OPERATIONS | UID_OPERATIONS | {"projects", "organizations", "billing_accounts"}


def adapt_page(
    operation: str,
    payload: object,
    *,
    cursor: str = "0",
    page_num: int = 1,
) -> PageResult:
    """Translate endpoint-specific envelopes without inventing counts or identities."""
    if operation == "environment":
        if not isinstance(payload, Mapping):
            raise NotehubResponseError("Expected environment mapping")
        rows = [
            {"name": name, "scope": scope, "value": "[masked]"}
            for scope, values in payload.items()
            if scope != "environment_variable_notes" and isinstance(values, Mapping)
            for name in values
        ]
        envelope: Mapping[str, Any] = {}
    else:
        envelope = payload if isinstance(payload, Mapping) else {}
        key = COLLECTION_KEYS.get(operation)
        if key is not None:
            values = envelope.get(key, [])
        elif isinstance(payload, list):
            values = payload
        elif isinstance(payload, Mapping):
            values = [dict(payload)]
        else:
            raise NotehubResponseError("Expected record or collection")
        if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
            raise NotehubResponseError("Expected collection of records")
        rows = deepcopy(values)
    has_more = envelope.get("has_more")
    if has_more is not None and type(has_more) is not bool:
        raise NotehubResponseError("Expected boolean has_more")
    if has_more is None and operation in {"projects", "devices", "fleet_devices"}:
        has_more = len(rows) == PAGE_SIZE
    next_cursor = envelope.get("next_cursor")
    if next_cursor is not None and not isinstance(next_cursor, str):
        raise NotehubResponseError("Expected string next_cursor")
    if (
        operation in {"events", "fleet_events"}
        and has_more
        and (not next_cursor or next_cursor == cursor)
    ):
        raise NotehubResponseError("Event cursor missing or repeated; restart the query")
    keys: list[str] = []
    occurrences: dict[str, int] = {}
    for index, row in enumerate(rows):
        identity = (
            row.get("session") if operation == "sessions" else row.get("event") or row.get("uid")
        )
        if not isinstance(identity, str) or not identity:
            identity = f"anonymous:{cursor}:{page_num}:{index}"
        count = occurrences.get(identity, 0)
        occurrences[identity] = count + 1
        candidate = identity if count == 0 else f"{identity}#{count}"
        while candidate in keys:
            candidate += "#"
        keys.append(candidate)
    return PageResult(
        rows=tuple(rows),
        row_keys=tuple(keys),
        has_more=has_more,
        next_cursor=next_cursor,
        page_num=page_num
        if operation in {"projects", "devices", "fleet_devices", "sessions"}
        else None,
    )


def _balance_history_filters(query: Query) -> BalanceHistoryFilters | None:
    """Adapt wire query dates to the balance-history facade's typed filter contract."""
    params = query.to_query_params()
    start_date = params.get("startDate")
    end_date = params.get("endDate")
    if start_date is None and end_date is None:
        return None
    if (start_date is not None and type(start_date) is not int) or (
        end_date is not None and type(end_date) is not int
    ):
        raise ValueError("Balance history date filters must be Unix-second integers")
    return BalanceHistoryFilters(start_date=start_date, end_date=end_date)


class TUIReadService:
    """Borrow a client and execute only explicitly enumerated read operations."""

    def __init__(self, client: NotehubClient) -> None:
        self.client = client
        self._slots = asyncio.Semaphore(2)

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
        """Read one bounded result; preserve typed client errors for the UI."""
        if operation not in OPERATIONS:
            raise ValueError("Unknown read operation")
        if operation in PROJECT_OPERATIONS and not project_uid:
            raise ValueError("Select a project first")
        if operation in UID_OPERATIONS and not uid:
            raise ValueError("Select a record first")
        if type(page_num) is not int or page_num < 1:
            raise ValueError("page_num must be positive")
        async with self._slots:
            with operation_context(operation):
                payload = await self._read(
                    operation, project_uid or "", uid or "", query or Query(), cursor, page_num
                )
        return adapt_page(operation, payload, cursor=cursor, page_num=page_num)

    async def _read(
        self,
        operation: str,
        project: str,
        uid: str,
        query: Query,
        cursor: str,
        page: int,
    ) -> Any:
        client = self.client
        numbered = Pagination(page_size=PAGE_SIZE, page_num=page)
        if operation == "projects":
            params = query.to_query_params() | numbered.to_query_params()
            return await client.projects.list(filters=Query.from_value(params))
        if operation == "project":
            return await client.projects.get(project)
        if operation == "events":
            return await client.events.list(
                project,
                filters=query,
                pagination=CursorPagination(cursor=cursor, page_size=PAGE_SIZE),
            )
        if operation == "devices":
            return await client.devices.list(project, filters=query, pagination=numbered)
        if operation == "device":
            return await client.devices.get(project, uid, filters=query)
        if operation == "latest":
            return await client.devices.latest(project, uid, filters=query)
        if operation == "sessions":
            return await client.devices.list_sessions(
                project, uid, filters=query, pagination=numbered
            )
        if operation == "environment":
            return await client.devices.get_environment(project, uid, filters=query)
        if operation == "fleets":
            return await client.fleets.list(project, filters=query)
        if operation == "fleet_devices":
            return await client.devices.list_for_fleet(
                project, uid, filters=query, **numbered.to_query_params()
            )
        if operation == "fleet_events":
            return await client.events.list_for_fleet(
                project, uid, filters=query, cursor=cursor, pageSize=PAGE_SIZE
            )
        if operation == "routes":
            return await client.routes.list(project, filters=query)
        if operation == "jobs":
            return await client.jobs.list(project, filters=query)
        if operation == "monitors":
            return await client.monitors.list(project, filters=query)
        if operation == "usage":
            return await client.usage.get(project, filters=query)
        if operation == "organizations":
            return await client.organizations.list(filters=query)
        if operation == "organization":
            return await client.organizations.get(uid)
        if operation == "organization_history":
            return await client.organizations.balance_history(
                uid, filters=_balance_history_filters(query)
            )
        if operation == "billing_accounts":
            return await client.billing_accounts.list(filters=query)
        if operation == "billing_account":
            return await client.billing_accounts.get(uid)
        if operation == "billing_history":
            return await client.billing_accounts.balance_history(
                uid, filters=_balance_history_filters(query)
            )
        raise ValueError("Unknown read operation")


class SimulationProjectService:
    """Expose one local Simulation run through the ordinary Notehub read facades."""

    def __init__(
        self,
        simulation: Simulation,
        scenario_name: str,
        client_context: AsyncContextManager[NotehubClient],
        reader: ReadService,
    ) -> None:
        self.simulation = simulation
        self.scenario_name = scenario_name
        self._client_context = client_context
        self.reader = reader
        self.project_uid = simulation.scenario.projects[0].uid
        self._closed = False
        self._active_reads = 0
        self._reads_drained = asyncio.Event()
        self._reads_drained.set()

    @classmethod
    async def open(
        cls, simulation: Simulation, scenario_name: str, *, observer: Observer | None = None
    ) -> SimulationProjectService:
        """Start a local-only client context for an existing scenario run."""
        client_context = simulation.client(observer=observer)
        try:
            client = await client_context.__aenter__()
        except BaseException:
            simulation.close()
            raise
        return cls(simulation, scenario_name, client_context, TUIReadService(client))

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
        """Delegate a bounded read through NotehubClient's local simulation transport."""
        if self._closed:
            raise RuntimeError("Simulation project is closed")
        self._active_reads += 1
        self._reads_drained.clear()
        try:
            return await self.reader.read(
                operation,
                project_uid=project_uid,
                uid=uid,
                query=query,
                cursor=cursor,
                page_num=page_num,
            )
        finally:
            self._active_reads -= 1
            if self._active_reads == 0:
                self._reads_drained.set()

    async def close(self) -> None:
        """Close the local HTTP client context and its in-process scenario run."""
        if self._closed:
            return
        self._closed = True
        await self._reads_drained.wait()
        try:
            await self._client_context.__aexit__(None, None, None)
        finally:
            self.simulation.close()


class ReadService(Protocol):
    """Structural seam shared by production and deterministic local reads."""

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
        """Read one bounded page from the supplied project and record scope."""
        ...


__all__ = ["PAGE_SIZE", "ReadService", "SimulationProjectService", "TUIReadService", "adapt_page"]
