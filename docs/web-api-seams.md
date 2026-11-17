# Web cockpit API seams

Live Notehub operations use one same-origin FastAPI app for session bootstrap, named reads, resource URLs, and project event SSE. The SPA owns navigation, transient interaction state, and browser-local favorites. This keeps the Python resource facades as the single path to Notehub. A separate, session-local simulation mode supports deterministic scenario controls without sending requests to Notehub.

## Current contract

- `POST /api/commands` accepts `{ "command": "devices.list", "args": { "project_uid": "app:...", "page_size": 50 } }`. The explicit registry contains reads only. Unknown commands fail closed; page size and event filter keys are bounded.
- Named `GET /api/...` routes expose the same read operations for direct links and other local clients. Event query parameters are translated to the command filter shape.
- `GET /api/projects/{project_uid}/stream/events` relays cursor pages as SSE batches, with `Last-Event-ID` for reconnects. The browser owns deduplication and freshness display.
- `GET /api/simulations`, `POST /api/simulation/start`, `GET /api/simulation`, and `POST /api/simulation/control` load named or TOML scenarios and advance only the current browser session's local run. Normal project, device, and event reads continue through `NotehubClient` with the simulation transport.
- `POST /api/simulation/stop` returns to the live client retained by that browser session. Ending a simulation-only session leaves the workspace chooser available. The live client and simulation client have separate lifetimes.
- The web process shares an opt-in `RequestPacer` across its Notehub clients, reserving at most six requests per minute. A rate-limited read is retried once after the pacer observes `Retry-After`; a write will need its own retry policy. The event stream polls once per minute, and the opening overview loads only project and device summaries.
- The PAT lives in the local server session. The launch fragment is exchanged for an HTTP-only cookie and removed from browser history. Simulation state and upload labels are session-local; neither the PAT nor scenario contents are written to browser storage.

## Next command requests

Add command families only when a workflow needs them. Give each command a typed argument schema, an explicit permission and scope, a documented result, and a stable error code. Avoid a generic `method/path/body` proxy that would bypass the resource facade and make review harder.

Candidate workflows:

| Operator task | API seam | Why it helps |
| --- | --- | --- |
| Change device environment | `device.environment.stage`, then `device.environment.apply` | Resolve targets, compare current and proposed keys, redact values in the preview, and require explicit apply. |
| Add or update a note | `note.stage`, then `note.apply` | Validate body and target through `compose/`, show the exact intended write, and return Notehub's result. |
| Apply one action to several devices | `batch.stage`, then `batch.apply` | Bound fan-out, preview per-target effects, report partial success precisely, and support retry of failed targets. |
| Investigate an event | `events.search` with a typed filter model | Share URL-backed searches and return a bounded page without duplicating filter logic in the SPA. |

For staged writes, the server should issue a short-lived preview ID tied to the current session, command, target, and validated payload. Apply should require that ID and an idempotency key, recheck relevant state before sending the write, and return per-target outcomes. A successful Notehub API response must be labeled as **accepted by Notehub**, not as device synchronization or execution. Keep the preview and audit summary free of secret values. These are design candidates; no write command is registered yet.

## Watch and notifications

Favorite means quick access. Watch would be a separate browser-local preference for matching future events while the dashboard is open. Start with in-app UI-SDK toasts after the SSE baseline is established; suppress catch-up batches and group bursts by device. Link a toast to a URL-backed event filter and inspector. The browser needs no new server write for this first version.

Desktop notifications are a possible later opt-in layer on Watch. Request permission only after a clear user action, show a test notification, and keep event bodies and secret values out of notification text. The dashboard should promise delivery only while its page is open; reliable alerts after closing it would require a separate server-side subscription and delivery design. No OS notification permission is requested today.

## Route and state boundary

Keep project/resource identity and applied event filters in the URL. Store only small, versioned browser preferences such as favorite UIDs and preferred project locally. Keep the PAT, event bodies, revealed environment values, and uncommitted form data out of browser storage. Account views must remain useful for credentials that can see organizations or billing accounts but no projects.

The artwork catalog at [`temp/spa-artwork/README.md`](../temp/spa-artwork/README.md) is the visual and journey reference for future iterations.
