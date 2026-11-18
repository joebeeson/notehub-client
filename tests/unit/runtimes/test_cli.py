"""Credential input and request boundaries of the command runtime."""

import io
import json
from pathlib import Path

import click
import httpx
import pytest
import respx
from click.testing import CliRunner

from notehub_client.runtimes.cli import commands as cli_commands
from notehub_client.runtimes.cli import create_cli
from notehub_client.runtimes.cli.options import read_text_source


@pytest.mark.parametrize(
    ("limit", "count", "checkpoint_value", "requested"),
    [
        (None, 4, "terminal", ["start", "page-1", "page-2"]),
        (1, 1, "start", ["start"]),
        (2, 2, "page-1", ["start"]),
        (3, 3, "page-1", ["start", "page-1"]),
    ],
)
@respx.mock
def test_event_export_checkpoints_only_complete_pages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    limit: int | None,
    count: int,
    checkpoint_value: str,
    requested: list[str],
) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "synthetic-pat")
    checkpoint = tmp_path / "cursor"
    checkpoint.write_text("start", encoding="utf-8")
    records = [{"event": f"evt:{number}"} for number in range(4)]
    route = respx.get("https://api.notefile.net/v1/projects/app:test/events").mock(
        side_effect=[
            httpx.Response(
                200, json={"events": records[:2], "has_more": True, "next_cursor": "page-1"}
            ),
            httpx.Response(
                200, json={"events": records[2:], "has_more": True, "next_cursor": "page-2"}
            ),
            httpx.Response(200, json={"events": [], "has_more": False, "next_cursor": "terminal"}),
        ]
    )
    options = ["--limit", str(limit)] if limit is not None else []
    result = CliRunner().invoke(
        create_cli(),
        [
            "--project",
            "app:test",
            "events",
            "export",
            "--cursor",
            "start",
            "--page-size",
            "2",
            "--checkpoint-file",
            str(checkpoint),
            *options,
        ],
    )
    assert result.exit_code == 0, result.output
    assert [json.loads(line) for line in result.stdout.splitlines()] == records[:count]
    assert checkpoint.read_text(encoding="utf-8") == checkpoint_value
    assert [call.request.url.params["cursor"] for call in route.calls] == requested


@respx.mock
def test_event_export_preserves_checkpoint_if_record_write_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "synthetic-pat")
    checkpoint = tmp_path / "cursor"
    checkpoint.write_text("start", encoding="utf-8")
    emit = cli_commands.emit_ndjson

    def emit_until_failure(record, *, show_secrets=False):
        if record["event"] == "evt:2":
            raise OSError("synthetic output failure")
        emit(record, show_secrets=show_secrets)

    monkeypatch.setattr(cli_commands, "emit_ndjson", emit_until_failure)
    respx.get("https://api.notefile.net/v1/projects/app:test/events").mock(
        return_value=httpx.Response(
            200,
            json={
                "events": [{"event": "evt:1"}, {"event": "evt:2"}],
                "has_more": False,
                "next_cursor": "terminal",
            },
        )
    )
    result = CliRunner().invoke(
        create_cli(),
        [
            "--project",
            "app:test",
            "events",
            "export",
            "--cursor",
            "start",
            "--checkpoint-file",
            str(checkpoint),
        ],
    )
    assert isinstance(result.exception, OSError)
    assert json.loads(result.stdout) == {"event": "evt:1"}
    assert checkpoint.read_text(encoding="utf-8") == "start"


@pytest.mark.parametrize(
    ("output_format", "options", "wire_pagination"),
    [
        ("human", ["--page-num", "2"], {"pageNum": "2"}),
        ("json", ["--cursor", "saved"], {"cursor": "saved"}),
        ("ndjson", [], {}),
    ],
)
@respx.mock
def test_cli_lists_one_device_session_page(
    monkeypatch: pytest.MonkeyPatch,
    output_format: str,
    options: list[str],
    wire_pagination: dict[str, str],
) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "synthetic-pat")
    record = {"session": "session-1", "session_began": 100, "session_ended": 110}
    payload: dict[str, object] = {"sessions": [record], "has_more": False}
    if output_format == "json":
        payload["next_cursor"] = "terminal"
    route = respx.get(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:one/sessions"
    ).mock(return_value=httpx.Response(200, json=payload))
    result = CliRunner().invoke(
        create_cli(),
        [
            "--project",
            "app:test",
            "--format",
            output_format,
            "devices",
            "sessions",
            "dev:one",
            *options,
        ],
    )
    assert result.exit_code == 0, result.output
    assert route.call_count == 1
    assert dict(route.calls[0].request.url.params) == {"pageSize": "25", **wire_pagination}
    if output_format == "human":
        assert "Session UID" in result.output and "session-1" in result.output
    elif output_format == "json":
        assert json.loads(result.output) == payload
    else:
        assert [json.loads(line) for line in result.output.splitlines()] == [record]


@respx.mock
def test_cli_shows_terminal_session_checkpoint_on_an_empty_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "synthetic-pat")
    respx.get("https://api.notefile.net/v1/projects/app:test/devices/dev:one/sessions").mock(
        return_value=httpx.Response(
            200, json={"sessions": [], "has_more": False, "next_cursor": "terminal"}
        )
    )
    result = CliRunner().invoke(
        create_cli(), ["--project", "app:test", "devices", "sessions", "dev:one", "--cursor", "0"]
    )
    assert result.exit_code == 0, result.output
    assert "No sessions on this page" in result.output
    assert "resume cursor terminal" in result.output


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--cursor", ""], "nonempty string"),
        (["--cursor", "0", "--page-num", "1"], "cannot be combined"),
    ],
)
@respx.mock
def test_cli_rejects_invalid_session_pagination(options: list[str], message: str) -> None:
    result = CliRunner().invoke(
        create_cli(), ["--project", "app:test", "devices", "sessions", "dev:one", *options]
    )
    assert result.exit_code == 2
    assert message in result.output
    assert not respx.calls


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        pytest.param([], [], id="no-file-selector"),
        pytest.param(
            ["--query-json", '{"files":["a.qo","b.qo"]}'],
            ["a.qo", "b.qo"],
            id="repeated-raw-values",
        ),
        pytest.param(
            ["--query-json", '{"files":["a.qo","b.qo"]}', "--file", "c.qo"],
            ["a.qo,b.qo,c.qo"],
            id="raw-values-plus-flag",
        ),
    ],
)
@respx.mock
def test_events_list_preserves_file_selectors(
    monkeypatch: pytest.MonkeyPatch, options: list[str], expected: list[str]
) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "synthetic-pat")
    route = respx.get("https://api.notefile.net/v1/projects/app:test/events").mock(
        return_value=httpx.Response(200, json={"events": [], "has_more": False})
    )
    result = CliRunner().invoke(
        create_cli(),
        ["--project", "app:test", "--format", "json", "events", "list", *options],
    )
    assert result.exit_code == 0, result.output
    assert route.call_count == 1
    assert route.calls[0].request.url.params.get_list("files") == expected


@respx.mock
def test_events_list_rejects_conflicting_selector_without_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "synthetic-pat")
    result = CliRunner().invoke(
        create_cli(),
        [
            "--project",
            "app:test",
            "events",
            "list",
            "--query-json",
            '{"deviceUID":123}',
            "--device",
            "dev:one",
        ],
    )
    assert result.exit_code == 2
    assert "query parameter 'deviceUID' must contain strings" in result.output
    assert not respx.calls


class TerminalInput(io.BytesIO):
    """An in-memory terminal for Click's isolated stdin wrapper."""

    def isatty(self) -> bool:
        return True


@pytest.mark.parametrize("valid", [True, False], ids=["utf8-file", "invalid-json"])
@respx.mock
def test_cli_environment_file_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, valid: bool
) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "synthetic-pat")
    source = tmp_path / "values.json"
    values = {"mode": "静音", "interval": "60"}
    source.write_text(
        json.dumps(values, ensure_ascii=False) if valid else '{"mode": "private-payload"',
        encoding="utf-8",
    )
    route = respx.put(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:test/environment_variables"
    ).mock(return_value=httpx.Response(204))
    result = CliRunner().invoke(
        create_cli(),
        [
            "--project",
            "app:test",
            "--yes",
            "--format",
            "json",
            "devices",
            "env",
            "set",
            "dev:test",
            "--values",
            str(source),
        ],
    )
    if valid:
        assert result.exit_code == 0, result.output
        assert route.call_count == 1
        assert json.loads(route.calls[0].request.content) == {
            "environment_variables": {"mode": "静音", "interval": "60"}
        }
        assert "静音" not in result.output
    else:
        assert result.exit_code != 0
        assert "not valid JSON" in result.output
        assert "private-payload" not in result.output
        assert not respx.calls


@pytest.mark.parametrize(
    ("command", "path"),
    [
        pytest.param(
            ["devices", "env", "delete", "dev:test", "mode"],
            "devices/dev:test/environment_variables/mode",
            id="environment-delete",
        ),
        pytest.param(
            ["notes", "delete", "dev:test", "readings.db", "reading"],
            "devices/dev:test/notes/readings.db/reading",
            id="note-delete",
        ),
    ],
)
@pytest.mark.parametrize("choice", ["decline", "accept", "yes", "noninteractive"])
@respx.mock
def test_cli_write_confirmation_controls_requests(
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
    path: str,
    choice: str,
) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "synthetic-pat")
    route = respx.delete(f"https://api.notefile.net/v1/projects/app:test/{path}").mock(
        return_value=httpx.Response(204)
    )
    args = ["--project", "app:test", "--format", "json"]
    if choice == "yes":
        args.append("--yes")
    terminal = TerminalInput(b"y\n" if choice == "accept" else b"n\n")
    result = CliRunner().invoke(
        create_cli(),
        [*args, *command],
        input=terminal if choice in {"decline", "accept"} else b"",
    )
    if choice in {"accept", "yes"}:
        assert result.exit_code == 0, result.output
        assert route.call_count == 1
        assert len(respx.calls) == 1
    else:
        assert result.exit_code != 0
        assert not respx.calls
        assert "Aborted" in result.output if choice == "decline" else "--yes" in result.output
    assert "synthetic-pat" not in result.output


@respx.mock
def test_cli_reads_unicode_note_body_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTEHUB_TOKEN", "synthetic-pat")
    route = respx.post(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:test/notes/readings.qi"
    ).mock(return_value=httpx.Response(204))
    body = {"label": "温度 🌡️"}
    result = CliRunner().invoke(
        create_cli(),
        [
            "--project",
            "app:test",
            "--format",
            "json",
            "notes",
            "add-qi",
            "dev:test",
            "readings.qi",
            "--body",
            "-",
        ],
        input=json.dumps(body, ensure_ascii=False),
    )
    assert result.exit_code == 0, result.output
    assert route.call_count == 1
    assert json.loads(route.calls[0].request.content) == {"body": body}


@respx.mock
def test_cli_reads_token_from_stdin_and_runs_a_bounded_project_read() -> None:
    route = respx.get("https://api.notefile.net/v1/projects").mock(
        return_value=httpx.Response(200, json={"projects": [{"uid": "app:test"}]})
    )
    result = CliRunner().invoke(
        create_cli(),
        ["--token-file", "-", "--format", "json", "projects", "list"],
        input="synthetic-pat\n",
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["projects"] == [{"uid": "app:test"}]
    assert route.call_count == 1
    assert route.calls[0].request.headers["Authorization"] == "Bearer synthetic-pat"
    assert "synthetic-pat" not in result.output


def test_cli_rejects_competing_token_and_payload_stdin_before_reading() -> None:
    with pytest.raises(click.UsageError, match="only one"):
        # The dash selects stdin; it is not a credential.
        read_text_source("-", token_file="-", label="payload")  # noqa: S106
