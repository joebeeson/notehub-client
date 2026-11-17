# Tests

`pytest` runs the local unit suite by default. Keep remote or end-to-end checks in a future
`tests/e2e/` tree and invoke that tree explicitly; define its opt-in command and required
credentials when those checks are introduced. Mark those tests with `pytest.mark.e2e`; pytest also
collects doctests from the package source.

The shared test fixture clears `NOTEHUB_TOKEN` before each test so a developer's local credential
cannot change startup behavior or cause unit tests to contact Notehub. Tests for credential handling
set their own controlled values with `monkeypatch`.

## Layout

- Put focused unit tests in `tests/unit/test_<domain>.py`.
- When a domain grows, move its tests into `tests/unit/<domain>/` and split by concern, such as
  `models`, `validation`, and `pagination`.
- Keep a test beside the narrowest relevant domain. Put shared fixtures in a `conftest.py` at the
  nearest common directory, and keep one-off setup in the test that uses it.
- Use `pytest.mark.parametrize` when cases share the same behavior and assertion, with readable IDs
  for distinct cases. Keep separate tests when the expected behavior or setup differs materially.
- Keep async tests explicitly marked with `pytest.mark.asyncio`; marker names are validated strictly.
- Use plain `assert` for values and `pytest.raises(ExpectedError, match=...)` for failures, checking
  the specific exception type and a stable message fragment.

## Textual visual snapshots

Textual tests use Pilot for interaction and the `pytest-textual-snapshot` plugin for intentional SVG
visual regression coverage. Current snapshots pin the Demo Events workspace at 80×24 and 140×42;
other TUI states and sizes remain covered by direct Pilot assertions.

Run the snapshots with:

```console
uv run --group test pytest tests/unit/runtimes/tui/test_visual_snapshots.py --no-cov -q
```

If a snapshot changes, inspect the generated `../temp/snapshot_report.html` before accepting an update. Once
the new rendering is reviewed, update only the snapshot tests whose changes are intended:

```console
uv run --group test pytest tests/unit/runtimes/tui/test_visual_snapshots.py --no-cov -q --snapshot-update
```

Snapshots are headless render evidence. They do not replace physical terminal checks for clipboard
behavior, font metrics, color handling, or terminal restoration.

## File-backed test data

`pytest-datadir` is available in the test dependency group. Keep short, unique response bodies inline
where their shape is easiest to understand beside the assertion. Use `datadir` for larger or
mutable per-test files in a directory beside the test module named after that module (for example,
`tests/unit/test_client/`). Put reusable immutable files in the nearest scope's `data/` directory
and use `shared_datadir`.

Run package line coverage with `uv run --group test pytest --cov=notehub_client --cov-report=term-missing`.

## Doctests

Use a short doctest in a public function or class docstring when a small, runnable example is clearer
than prose. Keep examples deterministic and free of real credentials. If examples need context that
would distract from the behavior, provide descriptive placeholders through pytest's
`doctest_namespace` fixture in the nearest applicable `conftest.py`. Avoid adding a fixture until an
example needs one.
