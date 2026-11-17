"""Reusable Click option bundles and query input normalization."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, TypeVar, cast

import click

from ...filters import Query
from ..helpers import click_options

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import TextIO

    from ...typing import QueryValue

CommandT = TypeVar("CommandT", bound=Callable[..., Any])
PAGE_SIZE = click.IntRange(1, 10_000)


def page_number_options(function: CommandT) -> CommandT:
    """Add bounded page-number pagination options to a command."""
    return click_options(
        click.option("--page-size", type=PAGE_SIZE, default=25, show_default=True),
        click.option("--page-num", type=click.IntRange(1), default=None),
    )(function)


def cursor_options(function: CommandT) -> CommandT:
    """Add bounded cursor pagination options to an event command."""
    return click_options(
        click.option("--page-size", type=PAGE_SIZE, default=25, show_default=True),
        click.option("--cursor", default="0", show_default=True),
    )(function)


def event_query_options(*, cursor_mode: bool = False) -> Callable[[CommandT], CommandT]:
    """Build the shared event selector decorator for page or cursor commands."""
    options = [
        click.option("--query-json", help="Flat JSON object using Notehub query keys."),
        click.option(
            "--query-file",
            metavar="PATH",
            help="Read a JSON query object from PATH or -.",
        ),
        click.option("--device", "device_uids", multiple=True, metavar="UID"),
        click.option("--file", "files", multiple=True, metavar="NAME"),
        click.option("--sensor", "sensor_uids", multiple=True, metavar="UID"),
        click.option("--fleet", "fleet_uids", multiple=True, metavar="UID"),
        click.option("--serial-number", "serial_numbers", multiple=True, metavar="VALUE"),
        click.option("--session", "session_uids", multiple=True, metavar="UID"),
        click.option("--event", "event_uids", multiple=True, metavar="UID"),
        click.option("--start-date", metavar="SECONDS|ISO-8601"),
        click.option("--end-date", metavar="SECONDS|ISO-8601"),
        click.option("--date-type", type=click.Choice(["captured", "uploaded"])),
        click.option("--system-files-only", is_flag=True),
        click.option("--since"),
    ]
    if not cursor_mode:
        options.extend(
            (
                click.option(
                    "--sort-by",
                    type=click.Choice(
                        [
                            "best_id",
                            "device_serial",
                            "device_uid",
                            "captured",
                            "modified",
                            "device_location",
                            "tower_location",
                            "triangulated_location",
                            "best_location",
                        ]
                    ),
                ),
                click.option("--sort-order", type=click.Choice(["asc", "desc"])),
            )
        )
    return click_options(*options)


def read_text_source(
    source: str,
    *,
    token_file: str | None,
    label: str,
    is_token_file: bool = False,
) -> str:
    """Read UTF-8 text from a file or stdin, rejecting competing stdin inputs."""
    if source == "-":
        if token_file == "-" and not is_token_file:  # noqa: S105
            raise click.UsageError(
                "standard input can be used by only one of --token-file and input files"
            )
        get_text_stream = cast("Callable[[str], TextIO]", click.get_text_stream)
        return get_text_stream("stdin").read()
    try:
        return Path(source).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise click.UsageError(f"Could not read {label} from {source!r}") from None


def read_json_source(source: str, *, token_file: str | None, label: str) -> Any:
    """Read and decode a JSON file or stdin without echoing its contents."""
    try:
        return json.loads(read_text_source(source, token_file=token_file, label=label))
    except json.JSONDecodeError as error:
        raise click.UsageError(
            f"{label} is not valid JSON at line {error.lineno}, column {error.colno}"
        ) from None


def event_query(
    *,
    token_file: str | None,
    query_json: str | None = None,
    query_file: str | None = None,
    device_uids: tuple[str, ...] = (),
    files: tuple[str, ...] = (),
    sensor_uids: tuple[str, ...] = (),
    fleet_uids: tuple[str, ...] = (),
    serial_numbers: tuple[str, ...] = (),
    session_uids: tuple[str, ...] = (),
    event_uids: tuple[str, ...] = (),
    start_date: str | None = None,
    end_date: str | None = None,
    date_type: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    system_files_only: bool = False,
    since: str | None = None,
) -> Query:
    """Compose raw Notehub query keys with common event selector switches."""
    if query_json is not None and query_file is not None:
        raise click.UsageError("use only one of --query-json or --query-file")

    base: Mapping[str, QueryValue] | None = None
    try:
        if query_json is not None:
            base = json.loads(query_json)
        elif query_file is not None:
            base = read_json_source(query_file, token_file=token_file, label="query file")
        query = Query.from_value(base) if base is not None else Query()
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise click.UsageError(f"invalid query input: {error}") from None

    try:
        append_values = (
            ("deviceUID", device_uids),
            ("files", files),
            ("sensorUID", sensor_uids),
            ("fleetUID", fleet_uids),
            ("serialNumber", serial_numbers),
            ("sessionUID", session_uids),
            ("eventUID", event_uids),
        )
        params = query.to_query_params()
        for key, additions in append_values:
            current = params.get(key)
            if not additions or current is None:
                continue
            if isinstance(current, str):
                continue
            if isinstance(current, tuple) and all(isinstance(item, str) for item in current):
                if key == "files":
                    params[key] = ",".join(current)
                continue
            raise click.UsageError(
                f"query parameter {key!r} cannot be combined with a selector switch"
            )
        query = Query.from_value(params)
        query = query.devices(*device_uids).files(*files).sensors(*sensor_uids)
        query = query.fleets(*fleet_uids).serial_numbers(*serial_numbers)
        query = query.sessions(*session_uids).events(*event_uids)

        scalar_options: tuple[tuple[str, str | None], ...] = (
            ("startDate", _date_value(start_date) if start_date is not None else None),
            ("endDate", _date_value(end_date) if end_date is not None else None),
            ("dateType", date_type),
            ("sortBy", sort_by),
            ("sortOrder", sort_order),
            ("since", since),
        )
        for key, value in scalar_options:
            if value is not None:
                if key in query:
                    raise click.UsageError(f"query parameter {key!r} was specified more than once")
                query = query.combine({key: value})
        if system_files_only:
            if "systemFilesOnly" in query:
                raise click.UsageError(
                    "query parameter 'systemFilesOnly' was specified more than once"
                )
            query = query.system_files_only()
    except (TypeError, ValueError) as error:
        if isinstance(error, click.UsageError):
            raise
        raise click.UsageError(f"invalid event selectors: {error}") from None
    return query


def _date_value(value: str) -> str:
    try:
        return str(int(value))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise click.UsageError(
                "dates must be Unix seconds or timezone-aware ISO-8601 values"
            ) from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise click.UsageError("ISO-8601 dates must include a timezone")
        return str(int(parsed.timestamp()))


__all__ = [
    "cursor_options",
    "event_query",
    "event_query_options",
    "page_number_options",
    "read_json_source",
    "read_text_source",
]
