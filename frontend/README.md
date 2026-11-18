# Dashboard frontend

Use Node 24 and a Python environment with the `web` extra. From a fresh
checkout, `uv sync --extra web` installs the extra and builds the initial
bundle. Run the following commands from the repository root when working on
the frontend.

```console
npm ci --prefix frontend
npm run check --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
uv run --no-sync python -m notehub_client web --no-launch
```

The build writes the dashboard bundle to the Python package's
`runtimes/web/static` directory. Open the URL printed by the web command.
When the Python build hook runs for an editable install, it reuses a bundle
only if the frontend inputs and every generated file still match its previous
build. Run `npm run build --prefix frontend` after editing the frontend in an
existing environment. A sync can reuse the installed editable wheel without
running the hook again.

For the HTTP routes, session modes, and browser storage boundary, see the
[web API guide](../docs/web-api-seams.md).

## Environment inspector smoke check

Run the opt-in Chromium smoke test from the repository root:

```console
npm ci --prefix frontend
npm exec --prefix frontend -- playwright install chromium
npm run test:browser --prefix frontend
```

The command rebuilds the production bundle and serves it on loopback port 4173.
It intercepts API requests with synthetic project and device data, requires no
Notehub credentials, and closes the server when the run ends. Keep the port free;
the harness refuses to reuse another server. The regular `npm test` command still
runs without an installed browser. Failure traces go in the ignored
`frontend/test-results` directory.

The automated check covers the sequence below, unexpected API calls, and browser
JavaScript errors.

The separate session smoke test uses the real Python web routes and a synthetic
upstream client:

```console
uv sync --extra web
npm run test:browser:session --prefix frontend
```

It starts its own loopback server on port 4174 and opens two tabs sharing a session
cookie. It checks cancellation of in-flight live reads when simulation starts,
the other tab's reload message, HTTP 204 for a stale stream reconnect, and fresh
streams after returning to live mode and reloading the second tab. Upstream call,
active-read, and client-creation counters verify the server behavior. The fixture
always uses a synthetic token and never connects to Notehub. HTTP failures and
browser exceptions fail the test. Both browser suites share the Playwright setup
and require the Chromium installation above.

Serve the built dashboard and use synthetic device records. A browser harness
can intercept the session and command responses while serving the production
bundle. Include two devices and return distinct ordinary values in the device,
effective, and default environment maps for each one.

1. Open the first device. Confirm that variable names appear and all values
   are masked.
2. Select **Reveal sensitive values**, confirm that all three scopes show their
   values, then select **Hide sensitive values** and confirm that masking returns.
3. Reveal the values, close the inspector, and confirm that its contents are
   cleared. Inspect the second device and check that its values start masked.
4. Delay the environment response, close the inspector, then release the
   response. Confirm that the closed inspector stays empty and that the
   synthetic values do not appear in either browser storage area.

