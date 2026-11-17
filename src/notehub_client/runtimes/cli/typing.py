"""Typed context and parameter shapes for the Click runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from ..typing import ClientFactory

__all__ = ["CLIContext", "EventQueryParams", "OutputFormat", "PageNumberParams"]

OutputFormat = Literal["human", "json", "ndjson"]


class CLIContext(TypedDict):
    """Values shared by commands through Click's root context."""

    token_file: str | None
    project_uid: str | None
    output_format: OutputFormat
    yes: bool
    show_secrets: bool
    client_factory: ClientFactory
    resolved_token: str | None


class PageNumberParams(TypedDict):
    """Keyword parameters added by the page-number option bundle."""

    page_size: int
    page_num: int | None


class EventQueryParams(TypedDict, total=False):
    """Keyword parameters added by the common event selector options."""

    query_json: str | None
    query_file: str | None
    device_uids: tuple[str, ...]
    files: tuple[str, ...]
    sensor_uids: tuple[str, ...]
    fleet_uids: tuple[str, ...]
    serial_numbers: tuple[str, ...]
    session_uids: tuple[str, ...]
    event_uids: tuple[str, ...]
    start_date: str | None
    end_date: str | None
    date_type: Literal["captured", "uploaded"] | None
    sort_by: str | None
    sort_order: Literal["asc", "desc"] | None
    system_files_only: bool
    since: str | None
