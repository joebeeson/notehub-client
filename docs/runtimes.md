# Runtime entry points

The Python client works without any runtime extras. Install the extra for the interface
you want, then select it through `notehub-client <runtime>` or
`python -m notehub_client <runtime>`.

| Runtime | Extra | Dedicated command | Purpose |
| --- | --- | --- | --- |
| `cli` | `cli` | `notehub` | Terminal commands and scripted reads and writes |
| `tui` | `tui` | `notehub-client-tui` | Interactive terminal workbench |
| `api` | `api` | `notehub-client-api` | Local HTTP API |
| `web` | `web` | `notehub-client-web` | Local browser dashboard |
| `mcp` | `mcp` | `notehub-client-mcp` | Read-only MCP server |

For example, `notehub-client web --help` shows dashboard options. The top-level
`notehub-client --help` lists runtime choices without loading their dependencies.
Selecting a runtime loads its optional libraries; missing declared dependencies produce
an installation hint for that extra.

The dashboard prints its URL and opens the browser after the local listener is
ready. Pass `--no-launch` to print the ready URL for manual use.

## CLI input and confirmations

Use `--token-file PATH` to read credentials from a file, or `--token-file -` to
read them from standard input. Payload and query file options also accept `-`.
Only one input may consume stdin in a command; credentials and a payload cannot
both come from stdin. Files are decoded as UTF-8; stdin uses Python's configured
text stream.

Operations that replace or delete existing data, including environment updates,
require confirmation at an interactive terminal. For noninteractive scripts,
pass the root `--yes` option explicitly:

```console
notehub --project app:example --yes devices env set dev:example --values values.json
```

Declining confirmation or omitting `--yes` in a noninteractive invocation issues
no write request. Add-note commands create new data without a confirmation prompt;
`--yes` is not a dry-run option. API acceptance does not establish device sync.

### Read device sessions

Browse by page number, or start a cursor read with `--cursor 0`:

```console
notehub --project app:example devices sessions dev:example --page-num 2
notehub --project app:example --format json devices sessions dev:example --cursor 0
```

Each invocation makes one page request. Use `--format json` to retain
`has_more` and `next_cursor` in scripts. Save a nonempty cursor after processing
the whole page, including an empty page or a page that reports `has_more: false`.
Resume with the saved cursor for the same project, device, and page size. A
session can appear again when Notehub updates it. `--format ndjson` emits only
session records, so use JSON if you need checkpoints.

### Resume an event export

Use `--checkpoint-file` for a separate file containing the last fully written
page's cursor. Standard output contains only NDJSON records.

```console
notehub --project app:example events export --checkpoint-file events.cursor > events.ndjson
```

To resume, pass the contents of `events.cursor` to `--cursor` and keep the same
project, filters, and page size. If a write fails or `--limit` stops partway
through a page, that page may replay. Deduplicate by event UID when appending
to existing output. Include `event` in any field projection used for this.
The checkpoint tracks flushed CLI output. A downstream consumer must manage
its own durability and replay.

## Inspect or launch from Python

`RUNTIMES` is a read-only mapping from runtime names to entry-point module paths.
Importing it or calling `runtime_names()` does not import the runtime packages.

```python
from notehub_client.runtimes import RUNTIMES, run_runtime, runtime_names

names = runtime_names()  # ("cli", "tui", "api", "web", "mcp")
module_path = RUNTIMES["web"]  # "notehub_client.runtimes.web"
run_runtime("web", ["--no-launch"])
```

`run_runtime()` is a synchronous process entry point: it can own an event loop,
start a server, or exit after argument parsing. To embed HTTP routes in your own
ASGI application, use `notehub_client.runtimes.api.create_app()` instead; see
[Web API seams](web-api-seams.md).

The API entry point lives in `api.server` because the `api` package also exposes
the shared application factory used by the dashboard. The mapping describes built-in
entry points; it is not a plugin-registration API.

## Read MCP resources

An MCP host can discover two JSON resource templates from the server:

| Resource URI | Matching tool |
| --- | --- |
| `notehub://projects/{project_uid}` | `get_project` |
| `notehub://projects/{project_uid}/devices/{device_uid}` | `get_device` |

The resource URI names the project explicitly. The matching tools use the
server's configured project when their project argument is omitted. Both
interfaces read through the same Notehub client. The credentials and their
project permissions govern what either interface can read.

## Build and verify distributions

`uv build` creates a source archive, then builds a wheel from it. Source archives
retain frontend sources and the npm lockfile; creating the archive alone does not
need Node. Building a wheel requires Node and npm, including when installing from
a source archive. Installed wheels run without Node.

Each regular wheel build installs the locked npm dependencies and rebuilds the
dashboard. Editable builds can reuse a verified local bundle. The editable
cache lives in `frontend/node_modules` and is excluded from distributions.

The wheel explicitly includes generated dashboard assets even though Git ignores
them. Verify runtime resources with:

```console
uv build
uv run --no-sync python scripts/check_wheel.py dist
uv run --no-sync python scripts/smoke_installed_wheel.py dist
uv build --wheel --out-dir dist/direct
uv run --no-sync python scripts/check_wheel.py dist/direct
```

CI checks both routes. The tag-triggered release workflow runs the same archive
verifier on the wheel it will upload. The verifier requires the dashboard shell, its local
script and stylesheet references, the favicon, TUI styles, packaged scenarios, and
the typing marker. It inspects wheels directly so checkout files cannot mask missing
package data. It also checks the Vite build manifest for missing dynamic chunks,
stylesheets, and assets.

The smoke check installs the built wheel and its `web` extra in an isolated
environment outside the checkout. With Node unavailable to the runtime, it
requests the dashboard shell and JavaScript entry point through the ASGI app,
then starts the packaged `sensor` simulation and reads its devices. CI runs it
on Python 3.11. The release job runs it before uploading.
