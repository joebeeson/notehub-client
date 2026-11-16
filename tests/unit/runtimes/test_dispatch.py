import sys
from collections.abc import Callable
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import notehub_client.runtimes as runtimes
from notehub_client.__main__ import cli_main, main, tui_main
from notehub_client.errors import NotehubDependencyError
from notehub_client.runtimes import run_runtime, runtime_names
from notehub_client.runtimes.cli import main as cli_runtime_main
from notehub_client.runtimes.tui import main as tui_runtime_main


def test_runtime_names_list_available_entry_points() -> None:
    assert runtime_names() == ("cli", "tui")


def test_run_runtime_loads_a_runtime_and_passes_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = SimpleNamespace(main=Mock())
    importer = Mock(return_value=runtime)
    monkeypatch.setattr(runtimes, "import_module", importer)

    run_runtime("cli", ["--help"])

    importer.assert_called_once_with("notehub_client.runtimes.cli")
    runtime.main.assert_called_once_with(["--help"])


def test_run_runtime_rejects_unknown_names() -> None:
    with pytest.raises(ValueError, match="Unknown runtime"):
        run_runtime("web")


def test_run_runtime_translates_optional_import_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_click(_module_path: str) -> None:
        raise ModuleNotFoundError("No module named 'click'", name="click")

    monkeypatch.setattr(runtimes, "import_module", missing_click)
    with pytest.raises(NotehubDependencyError) as captured:
        run_runtime("cli")

    assert captured.value.feature == "cli runtime"
    assert captured.value.extra == "cli"
    assert captured.value.missing_module == "click"


def test_run_runtime_reraises_unrelated_import_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_other_dependency(_module_path: str) -> None:
        raise ModuleNotFoundError("No module named 'unrelated'", name="unrelated")

    monkeypatch.setattr(runtimes, "import_module", missing_other_dependency)
    with pytest.raises(ModuleNotFoundError, match="unrelated"):
        run_runtime("cli")


def test_run_runtime_translates_missing_textual_from_runtime_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "textual", None)
    with pytest.raises(NotehubDependencyError) as captured:
        run_runtime("tui")

    assert captured.value.feature == "tui runtime"
    assert captured.value.extra == "tui"
    assert captured.value.missing_module == "textual"


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
        main(["web"])

    assert captured.value.code == 2
    error = capsys.readouterr().err
    assert "invalid choice" in error
    assert "web" in error


@pytest.mark.parametrize(
    ("entrypoint", "runtime"),
    [pytest.param(cli_main, "cli", id="legacy-cli"), pytest.param(tui_main, "tui", id="tui")],
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


def test_tui_runtime_reports_its_scaffold_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "textual", ModuleType("textual"))

    with pytest.raises(SystemExit, match="scaffolded but has no interface yet"):
        tui_runtime_main(["--help"])
