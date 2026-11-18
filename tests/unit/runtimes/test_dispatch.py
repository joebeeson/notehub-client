import importlib
import operator
import subprocess
import sys
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import pytest

import notehub_client.runtimes as runtimes
from notehub_client.__main__ import cli_main, main, mcp_main, tui_main, web_main
from notehub_client.errors import NotehubDependencyError
from notehub_client.runtimes import RUNTIMES, run_runtime, runtime_names
from notehub_client.runtimes.cli import main as cli_runtime_main
from notehub_client.runtimes.tui import main as tui_runtime_main


def test_runtime_names_list_available_entry_points() -> None:
    assert runtime_names() == ("cli", "tui", "api", "web", "mcp")


def test_runtime_metadata_is_read_only() -> None:
    assert tuple(RUNTIMES) == runtime_names()
    with pytest.raises(TypeError):
        operator.setitem(cast("dict[str, str]", RUNTIMES), "cli", "other.module")
    assert RUNTIMES["cli"] == "notehub_client.runtimes.cli"


def test_run_runtime_loads_a_runtime_and_passes_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = SimpleNamespace(main=Mock())
    importer = Mock(return_value=runtime)
    monkeypatch.setattr(runtimes, "import_module", importer)

    run_runtime("cli", ["--help"])

    importer.assert_called_once_with("notehub_client.runtimes.cli")
    runtime.main.assert_called_once_with(["--help"])


def test_run_runtime_rejects_unknown_names() -> None:
    with pytest.raises(ValueError, match="Unknown runtime"):
        run_runtime("unknown")


def test_run_runtime_preserves_import_failures_from_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_click(_module_path: str) -> None:
        raise ModuleNotFoundError("No module named 'click'", name="click")

    monkeypatch.setattr(runtimes, "import_module", missing_click)
    with pytest.raises(ModuleNotFoundError, match="click"):
        run_runtime("cli")


def test_run_runtime_reraises_unrelated_import_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_other_dependency(_module_path: str) -> None:
        raise ModuleNotFoundError("No module named 'unrelated'", name="unrelated")

    monkeypatch.setattr(runtimes, "import_module", missing_other_dependency)
    with pytest.raises(ModuleNotFoundError, match="unrelated"):
        run_runtime("cli")


def test_tui_runtime_reports_missing_textual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import notehub_client.runtimes.tui as tui

    with monkeypatch.context() as scoped:
        scoped.setitem(sys.modules, "textual", None)
        with pytest.raises(NotehubDependencyError, match="tui"):
            importlib.reload(tui)
    importlib.reload(tui)


def test_tui_runtime_reports_missing_rich(monkeypatch: pytest.MonkeyPatch) -> None:
    import notehub_client.runtimes.tui as tui

    with monkeypatch.context() as scoped:
        scoped.setitem(sys.modules, "rich", None)
        with pytest.raises(NotehubDependencyError, match="tui"):
            importlib.reload(tui)
    importlib.reload(tui)


def test_core_imports_without_textual_or_rich() -> None:
    script = """
import importlib.abc
import sys

class MissingRuntimeLibraries(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'rich', 'textual', 'click', 'fastapi', 'uvicorn', 'fastmcp'}:
            raise ModuleNotFoundError(f'No module named {fullname!r}', name=fullname.split('.')[0])

sys.meta_path.insert(0, MissingRuntimeLibraries())
import notehub_client
from notehub_client import NotehubClient
from notehub_client.runtimes import RUNTIMES, runtime_names
assert NotehubClient
assert tuple(RUNTIMES) == runtime_names()
assert len(RUNTIMES) == 5
try:
    import notehub_client.runtimes.tui
except notehub_client.errors.NotehubDependencyError as error:
    assert 'notehub-client[tui]' in str(error)
else:
    raise AssertionError('TUI imported without its declared optional libraries')
"""
    # This is a fixed in-test probe executed by the active interpreter.
    subprocess.run(  # noqa: S603
        [sys.executable, "-c", script], check=True, capture_output=True, text=True
    )


def test_run_runtime_reraises_unrelated_failures_from_runtime_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        main=Mock(side_effect=ModuleNotFoundError("No module named 'unrelated'", name="unrelated"))
    )
    monkeypatch.setattr(runtimes, "import_module", Mock(return_value=runtime))

    with pytest.raises(ModuleNotFoundError, match="unrelated"):
        run_runtime("tui")


def test_main_dispatches_an_explicit_runtime_and_arguments() -> None:
    with patch("notehub_client.__main__.run_runtime") as run:
        main(["cli", "--help"])

    run.assert_called_once_with("cli", ["--help"])


def test_main_rejects_unknown_runtime_names(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as captured:
        main(["unknown"])

    assert captured.value.code == 2
    error = capsys.readouterr().err
    assert "invalid choice" in error
    assert "unknown" in error


@pytest.mark.parametrize(
    ("entrypoint", "runtime"),
    [
        pytest.param(cli_main, "cli", id="legacy-cli"),
        pytest.param(tui_main, "tui", id="tui"),
        pytest.param(web_main, "web", id="web"),
        pytest.param(mcp_main, "mcp", id="mcp"),
    ],
)
def test_console_entrypoints_delegate_to_the_expected_runtime(
    entrypoint: Callable[[], None], runtime: str
) -> None:
    with patch("notehub_client.__main__.run_runtime") as run:
        entrypoint()

    run.assert_called_once_with(runtime, None)


def test_console_entrypoint_turns_missing_optional_dependencies_into_usage_errors() -> None:
    missing_dependency = NotehubDependencyError("cli runtime", "cli", "click")
    with patch("notehub_client.__main__.run_runtime", side_effect=missing_dependency):
        with pytest.raises(SystemExit, match="notehub-client:"):
            main(["cli"])


def test_cli_runtime_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as captured:
        cli_runtime_main(["--help"])

    assert captured.value.code == 0
    assert "Work with Blues Notehub" in capsys.readouterr().out


def test_tui_runtime_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as captured:
        tui_runtime_main(["--help"])
    assert captured.value.code == 0
    assert "terminal workbench" in capsys.readouterr().out
