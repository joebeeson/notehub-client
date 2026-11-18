# Contributing to notehub-client

Use Python 3.11 or newer, uv, and Node 24 with npm. The Python build hook
builds the dashboard when it prepares the editable install, so have Node and
npm on your path before syncing.

From the repository root, install the tools and optional runtimes:

```console
uv sync --locked --all-groups --all-extras
uv run --no-sync prek install --prepare-hooks
```

The Git hook is optional. You can run the same static checks without installing it.
If you use `just`, `just init` runs setup and installs the hook.

## Check your change

Run a focused test while you work. For example, this runs the client tests
without the coverage report:

```console
uv run --no-sync pytest --no-cov -q tests/unit/test_client.py
```

Run the repository checks before opening a pull request:

```console
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pyrefly check
uv run --no-sync bandit -c pyproject.toml -r src
uv run --no-sync vulture --config pyproject.toml src tests
uv run --no-sync pytest
```

Local hooks run static checks. CI runs pytest separately across Python 3.11
through 3.14. The default suite uses local fixtures and synthetic data. See the
[test guide](tests/README.md) for test layout, credential isolation, and how to
review terminal snapshot changes.

For browser changes, use the [frontend guide](frontend/README.md) for TypeScript
checks, the Node tests, a production build, and a manual smoke check. For
packaging changes, follow the [wheel verification commands](docs/runtimes.md#build-and-verify-distributions).

## Find the right place for a change

The [Python source map](src/README.md) shows how requests flow and where the
client, runtime, and simulation responsibilities meet.
The [maintenance batches](docs/maintenance-batches.md) group open TODOs for
implementation and review.

| If you are changing… | Start here |
| --- | --- |
| A Notehub operation or query | [Resource facades](src/notehub_client/resources/) and [filter builders](src/notehub_client/filters/) |
| A terminal, browser, HTTP, or MCP interface | [Optional runtimes](src/notehub_client/runtimes/) and the [runtime guide](docs/runtimes.md) |
| A payload contract or simulation | [Payload catalog guide](docs/payload-catalog.md) and [simulation guide](docs/simulation.md) |
| An onboarding example | [Runnable examples](examples/README.md) |

For a pull request, describe the behavior that changed and how you verified it.
For device writes, distinguish a request accepted by Notehub from synchronization
or execution on a device.
