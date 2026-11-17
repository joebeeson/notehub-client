"""Explicit read command catalog shared by HTTP routes and the dashboard."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ...client import NotehubClient
from ...filters import CursorPagination, Pagination

Command = Callable[[NotehubClient, Mapping[str, Any]], Awaitable[Any]]


def _uid(args: Mapping[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError(f"{name} must be a nonempty identifier")
    return value


def _page(args: Mapping[str, Any]) -> Pagination:
    size = args.get("page_size", 50)
    number = args.get("page_num")
    if type(size) is not int or not 1 <= size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    if number is not None and (type(number) is not int or number < 1):
        raise ValueError("page_num must be positive")
    return Pagination(page_size=size, page_num=number)


def _filters(args: Mapping[str, Any]) -> dict[str, Any]:
    value = args.get("filters", {})
    if not isinstance(value, dict) or len(value) > 20:
        raise ValueError("filters must be an object with at most 20 keys")
    allowed = {
        "files",
        "deviceUID",
        "sensorUID",
        "fleetUID",
        "serialNumber",
        "sessionUID",
        "eventUID",
        "startDate",
        "endDate",
        "dateType",
        "sortBy",
        "sortOrder",
        "systemFilesOnly",
        "selectFields",
        "since",
    }
    if set(value) - allowed:
        raise ValueError("unsupported filter key")
    return value


async def _projects(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    page = _page(args)
    params: dict[str, Any] = {"pageSize": page.page_size}
    if page.page_num is not None:
        params["pageNum"] = page.page_num
    return await client.projects.list(**params)


async def _project(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.projects.get(_uid(args, "project_uid"))


async def _fleets(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.fleets.list(_uid(args, "project_uid"))


async def _devices(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.devices.list(_uid(args, "project_uid"), pagination=_page(args))


async def _device(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.devices.get(_uid(args, "project_uid"), _uid(args, "device_uid"))


async def _sessions(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.devices.list_sessions(_uid(args, "project_uid"), _uid(args, "device_uid"))


async def _latest(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.devices.latest(_uid(args, "project_uid"), _uid(args, "device_uid"))


async def _environment(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.devices.get_environment(_uid(args, "project_uid"), _uid(args, "device_uid"))


async def _fleet_devices(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    page = _page(args)
    params: dict[str, Any] = {"pageSize": page.page_size}
    if page.page_num is not None:
        params["pageNum"] = page.page_num
    return await client.devices.list_for_fleet(
        _uid(args, "project_uid"), _uid(args, "fleet_uid"), **params
    )


async def _events(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    page = _page(args)
    cursor = args.get("cursor", "0")
    if not isinstance(cursor, str) or not cursor or len(cursor) > 512:
        raise ValueError("cursor must be a nonempty string of at most 512 characters")
    return await client.events.list(
        _uid(args, "project_uid"),
        **_filters(args),
        pagination=CursorPagination(cursor=cursor, page_size=page.page_size),
    )


async def _fleet_events(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.events.list_for_fleet(
        _uid(args, "project_uid"), _uid(args, "fleet_uid"), **_filters(args)
    )


async def _routes(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.routes.list(_uid(args, "project_uid"))


async def _jobs(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.jobs.list(_uid(args, "project_uid"))


async def _monitors(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.monitors.list(_uid(args, "project_uid"))


async def _usage(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.usage.get(_uid(args, "project_uid"))


async def _organizations(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.organizations.list()


async def _organization(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.organizations.get(_uid(args, "organization_uid"))


async def _organization_balance(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.organizations.balance_history(_uid(args, "organization_uid"))


async def _billing_accounts(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.billing_accounts.list()


async def _billing_account(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.billing_accounts.get(_uid(args, "billing_account_uid"))


async def _billing_balance(client: NotehubClient, args: Mapping[str, Any]) -> Any:
    return await client.billing_accounts.balance_history(_uid(args, "billing_account_uid"))


READ_COMMANDS: dict[str, Command] = {
    "projects.list": _projects,
    "projects.get": _project,
    "fleets.list": _fleets,
    "devices.list": _devices,
    "devices.get": _device,
    "devices.sessions": _sessions,
    "devices.latest": _latest,
    "devices.environment": _environment,
    "devices.for_fleet": _fleet_devices,
    "events.list": _events,
    "events.for_fleet": _fleet_events,
    "routes.list": _routes,
    "jobs.list": _jobs,
    "monitors.list": _monitors,
    "usage.get": _usage,
    "organizations.list": _organizations,
    "organizations.get": _organization,
    "organizations.balance_history": _organization_balance,
    "billing_accounts.list": _billing_accounts,
    "billing_accounts.get": _billing_account,
    "billing_accounts.balance_history": _billing_balance,
}


async def execute_read(client: NotehubClient, command: str, args: Mapping[str, Any]) -> Any:
    """Execute one allowlisted, read-only Notehub operation."""
    try:
        operation = READ_COMMANDS[command]
    except KeyError:
        raise ValueError("unknown read command") from None
    return await operation(client, args)
