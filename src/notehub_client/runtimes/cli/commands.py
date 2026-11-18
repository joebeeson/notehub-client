"""Click commands for Notehub project, device, event, and note workflows."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from contextlib import aclosing
from pathlib import Path
from typing import TYPE_CHECKING, cast

import click

from ...client import NotehubClient
from ...errors import NotehubError
from ...filters import CursorPagination, Pagination, Query
from ..helpers import RichProgressObserver, configure_rich_logging, run_async
from .options import (
    cursor_options,
    event_query,
    event_query_options,
    page_number_options,
    read_json_source,
    read_text_source,
)
from .output import emit_ndjson, emit_result, save_checkpoint
from .typing import CLIContext

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable
    from typing import Any, Unpack

    from ...typing import Event, JSONValue
    from ..typing import ClientFactory
    from .typing import EventQueryParams, OutputFormat, PageNumberParams


def create_cli(
    *,
    client_factory: ClientFactory | None = None,
    configure_logging: bool = False,
) -> click.Group:
    """Build the command group, optionally injecting a client factory."""
    factory = client_factory or NotehubClient

    @click.group()
    @click.version_option(package_name="notehub-client")
    @click.option(
        "--token-file",
        metavar="PATH",
        help="Read a bearer token from PATH or stdin (-).",
    )
    @click.option(
        "--project",
        "project_uid",
        envvar="NOTEHUB_PROJECT_UID",
        help="Project UID for project-scoped commands.",
    )
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["human", "json", "ndjson"]),
        default="human",
        show_default=True,
    )
    @click.option("--yes", is_flag=True, help="Skip confirmation prompts for writes.")
    @click.option("--show-secrets", is_flag=True, help="Reveal values marked sensitive in output.")
    @click.option(
        "--log-level",
        type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
        default="WARNING",
        show_default=True,
        help="Set the Rich console log level when run as a process entry point.",
    )
    @click.pass_context
    def cli(
        ctx: click.Context,
        token_file: str | None,
        project_uid: str | None,
        output_format: OutputFormat,
        yes: bool,
        show_secrets: bool,
        log_level: str,
    ) -> None:
        """Work with Blues Notehub from the command line."""
        if configure_logging:
            configure_rich_logging(log_level)
        context = CLIContext(
            token_file=token_file,
            project_uid=project_uid,
            output_format=output_format,
            yes=yes,
            show_secrets=show_secrets,
            client_factory=factory,
            resolved_token=None,
        )
        ctx.obj = context

    _add_project_commands(cli)
    _add_device_commands(cli)
    _add_event_commands(cli)
    _add_note_commands(cli)

    @cli.command("web")
    @click.option("--port", type=click.IntRange(0, 65535), default=0)
    @click.option("--no-launch", is_flag=True, help="print the URL without opening a browser")
    @click.option("--open", "open_browser", is_flag=True, hidden=True)
    @click.pass_context
    def web(ctx: click.Context, port: int, no_launch: bool, open_browser: bool) -> None:
        """Start the local browser dashboard."""
        from ..web import main as web_main

        state = _state(ctx)
        args = ["--port", str(port)]
        if no_launch:
            args.append("--no-launch")
        elif open_browser:
            args.append("--open")
        if state["project_uid"]:
            args.extend(("--project", state["project_uid"]))
        if state["token_file"]:
            if state["token_file"] == "-":  # noqa: S105
                raise click.UsageError("web runtime requires a token file path, not stdin")
            args.extend(("--token-file", state["token_file"]))
        web_main(args)

    return cli


def _add_project_commands(cli: click.Group) -> None:
    @cli.group()
    def projects() -> None:
        """Discover projects visible to the authenticated user."""

    @projects.command("list")
    @page_number_options
    @click.pass_context
    def list_projects(ctx: click.Context, **page: Unpack[PageNumberParams]) -> None:
        """List one bounded page of projects."""
        filters: dict[str, int] = {"pageSize": page["page_size"]}
        if page["page_num"] is not None:
            filters["pageNum"] = page["page_num"]
        query = Query.from_value(filters)
        _run(ctx, lambda client: client.projects.list(filters=query), records_key="projects")

    @projects.command("get")
    @click.argument("project_uid")
    @click.pass_context
    def get_project(ctx: click.Context, project_uid: str) -> None:
        """Fetch one project by UID."""
        _run(ctx, lambda client: client.projects.get(project_uid), entity="project")


def _add_device_commands(cli: click.Group) -> None:
    @cli.group()
    def devices() -> None:
        """List devices and manage device environment variables."""

    @devices.command("list")
    @page_number_options
    @click.pass_context
    def list_devices(ctx: click.Context, **page: Unpack[PageNumberParams]) -> None:
        """List one bounded page of devices in the selected project."""
        project_uid = _project(ctx)
        _run(
            ctx,
            lambda client: client.devices.list(
                project_uid,
                pagination=Pagination(page_size=page["page_size"], page_num=page["page_num"]),
            ),
            records_key="devices",
        )

    @devices.command("get")
    @click.argument("device_uid")
    @click.pass_context
    def get_device(ctx: click.Context, device_uid: str) -> None:
        """Fetch a device by UID in the selected project."""
        project_uid = _project(ctx)
        _run(ctx, lambda client: client.devices.get(project_uid, device_uid), entity="device")

    @devices.command("sessions")
    @click.argument("device_uid")
    @page_number_options
    @click.option("--cursor", help="Read session changes from 0 or a previous checkpoint.")
    @click.pass_context
    def list_sessions(
        ctx: click.Context,
        device_uid: str,
        page_size: int,
        page_num: int | None,
        cursor: str | None,
    ) -> None:
        """Fetch one page of sessions for a device."""
        if cursor == "":
            raise click.BadParameter("must be a nonempty string", param_hint="--cursor")
        if cursor is not None and page_num is not None:
            raise click.UsageError("--cursor cannot be combined with --page-num")
        project_uid = _project(ctx)
        pagination = (
            CursorPagination(cursor=cursor, page_size=page_size)
            if cursor is not None
            else Pagination(page_size=page_size, page_num=page_num)
        )
        _run(
            ctx,
            lambda client: client.devices.list_sessions(
                project_uid, device_uid, pagination=pagination
            ),
            records_key="sessions",
        )

    @devices.group("env")
    def environment() -> None:
        """Read and manage device environment variables."""

    @environment.command("get")
    @click.argument("device_uid")
    @click.pass_context
    def get_environment(ctx: click.Context, device_uid: str) -> None:
        """Show environment variable names and values for a device."""
        project_uid = _project(ctx)
        _run(
            ctx,
            lambda client: client.devices.get_environment(project_uid, device_uid),
            records_key="environment_variables",
        )

    @environment.command("set")
    @click.argument("device_uid")
    @click.option(
        "--values",
        "values_file",
        required=True,
        metavar="PATH",
        help="JSON object file or stdin (-).",
    )
    @click.pass_context
    def set_environment(ctx: click.Context, device_uid: str, values_file: str) -> None:
        """Add or update environment variables from a JSON object."""
        state = _state(ctx)
        project_uid = _project(ctx)
        _check_stdin(state, (values_file,))
        _resolve_token(state)
        values = read_json_source(
            values_file,
            token_file=state["token_file"],
            label="environment values",
        )
        if not isinstance(values, Mapping) or any(not isinstance(key, str) for key in values):
            raise click.UsageError("--values must contain a JSON object with string keys")
        variable_names = sorted(values)
        _confirm_write(
            ctx,
            f"Set environment variable(s) {', '.join(variable_names) or '(none)'} "
            f"on device {device_uid} in project {project_uid}?",
        )
        _run(
            ctx,
            _summarize(
                lambda client: client.devices.set_environment(project_uid, device_uid, values),
                action="devices.env.set",
                project_uid=project_uid,
                device_uid=device_uid,
                variables=variable_names,
            ),
            stdin_sources=(values_file,),
        )

    @environment.command("delete")
    @click.argument("device_uid")
    @click.argument("name")
    @click.pass_context
    def delete_environment(ctx: click.Context, device_uid: str, name: str) -> None:
        """Delete one environment variable from a device."""
        project_uid = _project(ctx)
        _confirm_write(
            ctx,
            f"Delete environment variable {name!r} from device {device_uid} "
            f"in project {project_uid}?",
        )
        _run(
            ctx,
            _summarize(
                lambda client: client.devices.delete_environment_variable(
                    project_uid, device_uid, name
                ),
                action="devices.env.delete",
                project_uid=project_uid,
                device_uid=device_uid,
                variable=name,
            ),
        )


def _add_event_commands(cli: click.Group) -> None:
    @cli.group()
    def events() -> None:
        """List or stream project events."""

    @events.command("list")
    @page_number_options
    @event_query_options()
    @click.pass_context
    def list_events(
        ctx: click.Context,
        page_size: int,
        page_num: int | None,
        **selectors: Unpack[EventQueryParams],
    ) -> None:
        """List one bounded page of events, preserving the response envelope."""
        project_uid = _project(ctx)
        state = _state(ctx)
        stdin_sources = _query_stdin(selectors)
        _check_stdin(state, stdin_sources)
        _resolve_token(state)
        query = event_query(token_file=state["token_file"], **selectors)
        page_params = {"pageSize": page_size}
        if page_num is not None:
            page_params["pageNum"] = page_num
        try:
            query = query.combine(page_params)
        except ValueError as error:
            raise click.UsageError(str(error)) from None
        _run(
            ctx,
            lambda client: client.events.list(
                project_uid,
                filters=query,
            ),
            stdin_sources=stdin_sources,
            records_key="events",
        )

    @events.command("export")
    @cursor_options
    @event_query_options(cursor_mode=True)
    @click.option("--limit", type=click.IntRange(1), help="Stop after this many events.")
    @click.option(
        "--checkpoint-file",
        type=click.Path(dir_okay=False, path_type=Path),
        help="Save the cursor after each fully written page.",
    )
    @click.pass_context
    def export_events(
        ctx: click.Context,
        page_size: int,
        cursor: str,
        limit: int | None,
        checkpoint_file: Path | None,
        **selectors: Unpack[EventQueryParams],
    ) -> None:
        """Stream events as NDJSON while following Notehub cursors."""
        project_uid = _project(ctx)
        state = _state(ctx)
        stdin_sources = _query_stdin(selectors)
        _check_stdin(state, stdin_sources)
        stdout = sys.stdout
        if checkpoint_file is not None:
            sources = (state["token_file"], selectors.get("query_file"))
            target = checkpoint_file.resolve()
            if any(
                source and source != "-" and Path(source).resolve() == target for source in sources
            ):
                raise click.UsageError("--checkpoint-file must differ from input files")
            try:
                same_output = os.path.samestat(checkpoint_file.stat(), os.fstat(stdout.fileno()))
            except (OSError, ValueError):
                same_output = False
            if same_output:
                raise click.UsageError("--checkpoint-file must differ from the NDJSON output")
        _resolve_token(state)
        query = event_query(token_file=state["token_file"], **selectors)
        conflicts = {"cursor", "pageSize", "pageNum", "sortBy", "sortOrder"}.intersection(query)
        if conflicts:
            raise click.UsageError(
                "events export controls cursor pagination; remove query keys: "
                + ", ".join(sorted(conflicts))
            )

        async def records(client: NotehubClient) -> AsyncIterator[Event]:
            count = 0
            pages = client.events.iter_pages(
                project_uid,
                filters=query,
                pagination=CursorPagination(cursor=cursor, page_size=page_size),
            )
            async with aclosing(pages):
                async for page in pages:
                    for event in page["events"]:
                        if count == limit:
                            return
                        yield event
                        count += 1
                    next_cursor = page.get("next_cursor")
                    if checkpoint_file is not None and next_cursor:
                        stdout.flush()
                        try:
                            save_checkpoint(checkpoint_file, next_cursor)
                        except OSError as error:
                            raise click.ClickException(
                                f"Could not save export checkpoint: {error.strerror}"
                            ) from None
                    if count == limit:
                        return

        async def export(client: NotehubClient) -> None:
            tracked = progress.track(
                records(client),
                description="Exporting events",
                total=limit,
            )
            async with aclosing(tracked):
                async for event in tracked:
                    emit_ndjson(event, show_secrets=state["show_secrets"])

        with RichProgressObserver(stderr=True) as progress:
            _run(ctx, export, stdin_sources=stdin_sources, emit=False)


def _add_note_commands(cli: click.Group) -> None:
    @cli.group()
    def notes() -> None:
        """Add, replace, and delete device notes."""

    @notes.command("add-qi")
    @click.argument("device_uid")
    @click.argument("notefile")
    @click.option(
        "--body",
        "body_file",
        required=True,
        metavar="PATH",
        help="JSON note body file or stdin (-).",
    )
    @click.pass_context
    def add_queue_note(ctx: click.Context, device_uid: str, notefile: str, body_file: str) -> None:
        """Add a queue-in note from a JSON object."""
        project_uid = _project(ctx)
        body = _read_note_body(ctx, body_file)
        _run(
            ctx,
            _summarize(
                lambda client: client.notes.add_qi(project_uid, device_uid, notefile, body),
                action="notes.add-qi",
                project_uid=project_uid,
                device_uid=device_uid,
                notefile=notefile,
            ),
            stdin_sources=(body_file,),
        )

    @notes.command("add-db")
    @click.argument("device_uid")
    @click.argument("notefile")
    @click.argument("note_id")
    @click.option(
        "--body",
        "body_file",
        required=True,
        metavar="PATH",
        help="JSON note body file or stdin (-).",
    )
    @click.pass_context
    def add_database_note(
        ctx: click.Context, device_uid: str, notefile: str, note_id: str, body_file: str
    ) -> None:
        """Add a database note from a JSON object."""
        project_uid = _project(ctx)
        body = _read_note_body(ctx, body_file)
        _run(
            ctx,
            _summarize(
                lambda client: client.notes.add_db(
                    project_uid, device_uid, notefile, note_id, body
                ),
                action="notes.add-db",
                project_uid=project_uid,
                device_uid=device_uid,
                notefile=notefile,
                note_id=note_id,
            ),
            stdin_sources=(body_file,),
        )

    @notes.command("update-db")
    @click.argument("device_uid")
    @click.argument("notefile")
    @click.argument("note_id")
    @click.option(
        "--body",
        "body_file",
        required=True,
        metavar="PATH",
        help="JSON note body file or stdin (-).",
    )
    @click.pass_context
    def update_database_note(
        ctx: click.Context, device_uid: str, notefile: str, note_id: str, body_file: str
    ) -> None:
        """Replace a database note body from a JSON object."""
        project_uid = _project(ctx)
        body = _read_note_body(ctx, body_file)
        _confirm_write(
            ctx,
            f"Replace note {note_id!r} in {notefile!r} on device {device_uid} "
            f"in project {project_uid}?",
        )
        _run(
            ctx,
            _summarize(
                lambda client: client.notes.update_db(
                    project_uid, device_uid, notefile, note_id, body
                ),
                action="notes.update-db",
                project_uid=project_uid,
                device_uid=device_uid,
                notefile=notefile,
                note_id=note_id,
            ),
            stdin_sources=(body_file,),
        )

    @notes.command("delete")
    @click.argument("device_uid")
    @click.argument("notefile")
    @click.argument("note_id")
    @click.pass_context
    def delete_note(ctx: click.Context, device_uid: str, notefile: str, note_id: str) -> None:
        """Delete a database note."""
        project_uid = _project(ctx)
        _confirm_write(
            ctx,
            f"Delete note {note_id!r} from {notefile!r} on device {device_uid} "
            f"in project {project_uid}?",
        )
        _run(
            ctx,
            _summarize(
                lambda client: client.notes.delete(project_uid, device_uid, notefile, note_id),
                action="notes.delete",
                project_uid=project_uid,
                device_uid=device_uid,
                notefile=notefile,
                note_id=note_id,
            ),
        )


def _read_note_body(ctx: click.Context, source: str) -> dict[str, JSONValue]:
    state = _state(ctx)
    _check_stdin(state, (source,))
    _resolve_token(state)
    value = read_json_source(source, token_file=state["token_file"], label="note body")
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise click.UsageError("--body must contain a JSON object with string keys")
    return value


def _run(
    ctx: click.Context,
    operation: Callable[[NotehubClient], Awaitable[Any]],
    *,
    stdin_sources: tuple[str, ...] = (),
    emit: bool = True,
    records_key: str | None = None,
    entity: str | None = None,
) -> Any:
    """Resolve credentials, own one client lifecycle, and translate user-facing errors."""
    state = _state(ctx)
    stdin_inputs = tuple(source for source in stdin_sources if source == "-")
    if state["token_file"] == "-" and stdin_inputs:  # noqa: S105
        raise click.UsageError(
            "standard input can be used by only one of --token-file and input files"
        )
    if len(stdin_inputs) > 1:
        raise click.UsageError("standard input can be used by only one input file")
    token = _resolve_token(state)

    async def execute() -> Any:
        async with state["client_factory"](token) as client:
            return await operation(client)

    try:
        result = run_async(execute())
    except click.ClickException:
        raise
    except NotehubError as error:
        raise click.ClickException(str(error)) from None
    except (TypeError, ValueError) as error:
        raise click.UsageError(str(error)) from None
    if emit:
        _emit(ctx, result, records_key=records_key, entity=entity)
    return result


def _summarize(
    operation: Callable[[NotehubClient], Awaitable[Any]],
    **details: Any,
) -> Callable[[NotehubClient], Awaitable[dict[str, Any]]]:
    """Return safe operation details without echoing request payload values."""

    async def execute(client: NotehubClient) -> dict[str, Any]:
        await operation(client)
        return details

    return execute


def _resolve_token(state: CLIContext) -> str:
    if state["resolved_token"] is not None:
        return state["resolved_token"]
    if state["token_file"] is not None:
        token = read_text_source(
            state["token_file"],
            token_file=state["token_file"],
            label="token file",
            is_token_file=True,
        ).strip()
    else:
        token = (os.getenv("NOTEHUB_TOKEN") or "").strip()
    if not token:
        raise click.UsageError("provide --token-file or set NOTEHUB_TOKEN")
    state["resolved_token"] = token
    return token


def _check_stdin(state: CLIContext, sources: tuple[str, ...]) -> None:
    stdin_sources = tuple(source for source in sources if source == "-")
    if state["token_file"] == "-" and stdin_sources:  # noqa: S105
        raise click.UsageError(
            "standard input can be used by only one of --token-file and input files"
        )
    if len(stdin_sources) > 1:
        raise click.UsageError("standard input can be used by only one input file")


def _state(ctx: click.Context) -> CLIContext:
    return cast("CLIContext", ctx.find_root().obj)


def _project(ctx: click.Context) -> str:
    project_uid = _state(ctx)["project_uid"]
    if not project_uid:
        raise click.UsageError("provide --project or set NOTEHUB_PROJECT_UID")
    return project_uid


def _emit(
    ctx: click.Context,
    value: object,
    *,
    records_key: str | None = None,
    entity: str | None = None,
) -> None:
    state = _state(ctx)
    emit_result(
        value,
        output_format=state["output_format"],
        records_key=records_key,
        entity=entity,
        show_secrets=state["show_secrets"],
    )


def _confirm_write(ctx: click.Context, prompt: str) -> None:
    state = _state(ctx)
    if state["yes"]:
        return
    if sys.stdin.isatty():
        click.confirm(prompt, abort=True)
        return
    raise click.UsageError("this write needs confirmation; pass --yes for non-interactive use")


def _query_stdin(selectors: EventQueryParams) -> tuple[str, ...]:
    query_file = selectors.get("query_file")
    return (query_file,) if query_file == "-" else ()


__all__ = ["create_cli"]
