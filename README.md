# notehub-client

An unofficial asynchronous Python client for the Blues Notehub REST API. It uses HTTPX, supports Personal Access Tokens and asynchronous token providers, and keeps API response data available as typed dictionaries without requiring a large runtime model layer.

## Installation

The package is being prepared for PyPI. Until it is published, install from GitHub:

```console
pip install "notehub-client @ git+https://github.com/joebeeson/notehub-client.git"
```

Create a Personal Access Token in Notehub's API Access settings and grant only the project roles and permissions your application needs. Keep tokens in a secret manager or environment variable.

## Quick start

```python
import asyncio
import os

from notehub_client import NotehubClient


async def main() -> None:
    async with NotehubClient(os.environ["NOTEHUB_TOKEN"]) as client:
        devices = await client.devices.collect("app:your-project-uid")
        for device in devices:
            print(device["uid"], device.get("last_activity"))

        async for event in client.events.iter("app:your-project-uid"):
            print(event.get("device"), event.get("file"), event.get("body"))


asyncio.run(main())
```

`NotehubClient` creates and closes its own `httpx.AsyncClient`. Supply `http_client=` to share a configured HTTPX client; the library will leave caller-supplied clients open. The client itself is an async context manager and can also be closed with `await client.aclose()`.

## Authentication

### Personal Access Token

Pass the token to `NotehubClient(token)`. The client adds it as a Bearer token to API requests. Authentication headers cannot be overridden through the generic request method.

### OAuth client credentials

Install the optional dependency with `pip install "notehub-client[oauth]"`. The Authlib-backed provider uses Notehub's form-encoded client-credentials exchange and renews tokens before the server-provided expiry:

```python
from notehub_client import NotehubClient
from notehub_client.oauth import NotehubOAuthTokenProvider

provider = NotehubOAuthTokenProvider(
    client_id="your-client-id",
    client_secret="your-client-secret",
)
try:
    async with NotehubClient(token_provider=provider) as client:
        project = await client.projects.get("app:your-project-uid")
finally:
    await provider.aclose()
```

The provider serializes token renewal so concurrent requests share one token exchange. Alternatively, pass any async callable that returns a nonempty bearer token as `token_provider=`. Keep an externally supplied provider alive for as long as the client uses it.

## Filters and pagination

Built-in immutable query objects implement the `QueryFilter` protocol and can be combined with explicit keyword parameters:

```python
from notehub_client import NotehubClient, filters

async with NotehubClient(token) as client:
    first_page = await client.devices.list(
        "app:your-project-uid",
        filters=filters.DeviceFilters(fleet_uids=("fleet:your-fleet-uid",)),
        pagination=filters.page(page_size=100, page_num=1),
    )

    recent = await client.events.list(
        "app:your-project-uid",
        filters=filters.EventFilters(
            files=("sensors.qo",),
            device_uids=("dev:your-device-uid",),
            start_date=1_735_689_600,
            date_type="captured",
            sort_order="asc",
        ),
    )

    account_history = await client.billing_accounts.balance_history(
        "billing:your-account-uid",
        filters=filters.BalanceHistoryFilters(start_date=1_735_689_600),
    )
```

Array filters are sent as repeated query keys, while `files` is serialized as Notehub's comma-separated value. A small application-specific object can implement `to_query_params()` and return a mapping; see the runtime-checkable `QueryFilter` protocol and `QueryValue` in `notehub_client.typing.query`. Duplicate keys between a filter and explicit parameters raise `ValueError` rather than silently overriding a value.

Event date and sort enums are available through the root `constants` module. Filters accept either their string values or the corresponding enums:

```python
from notehub_client import constants, filters

filters = filters.EventFilters(
    date_type=constants.EventDateTypeWire.CAPTURED,
    sort_by=constants.EventSortFieldWire.DEVICE_UID,
    sort_order=constants.EventSortOrderWire.ASC,
)
```

Compose immutable query values with filter factories and fluent methods:

```python
from notehub_client import constants, filters

selection = (
    filters.devices("dev:your-device-uid")
    .files("sensors.qo")
    .date_range(start=1_735_689_600)
    .date_type(constants.EventDateTypeWire.CAPTURED)
    .sort_by(constants.EventSortFieldWire.DEVICE_UID)
    .sort_order(constants.EventSortOrderWire.ASC)
)
```

`filters.combine(...)` combines independent query components and rejects duplicate wire keys. Direct immutable filter models remain available for endpoint-specific fields.

`DEFAULT_PAGE_SIZE`, `DEFAULT_TIMEOUT`, and `NOTEHUB_API_ORIGIN` are available from `notehub_client.constants` and the root `constants` module.

`devices.iter()` and `events.iter()` request pages lazily; `devices.collect()` and `events.collect()` materialize all matching items. Use `events.list()` when you need to persist a resume cursor: its envelope includes Notehub's `next_cursor`. Pass `filters.cursor(value)` as `pagination=` to resume `events.iter()`. Event iteration defaults to cursor `"0"` and detects missing or nonadvancing cursors when Notehub says more events remain. Device iteration uses Notehub's page-number pagination.

## API operations

The package provides named operations for common project and device reads, event pagination, Notes, and device environment variables. Domain facades group named operations under `client.projects`, `client.devices`, `client.events`, `client.fleets`, `client.organizations`, `client.billing_accounts`, `client.notes`, `client.routes`, `client.jobs`, `client.monitors`, and `client.usage`. The current named convenience methods are:

| API area | Named operations |
| --- | --- |
| Projects | `projects.get()`, `projects.list()` |
| Devices | `devices.list()`, `devices.iter()`, `devices.collect()`, `devices.get()`, `devices.list_sessions()`, `devices.latest()`, `devices.get_environment()` |
| Events | `events.list()`, `events.iter()`, `events.list_for_fleet()` |
| Notes | `notes.add_qi()`, `notes.add_db()`, `notes.update_db()`, `notes.delete()` |
| Fleets | `fleets.list()`, `devices.list_for_fleet()` |
| Organizations | `organizations.list()`, `organizations.get()`, `organizations.balance_history()` |
| Billing | `billing_accounts.list()`, `billing_accounts.get()`, `billing_accounts.balance_history()` |
| Routes, jobs, monitors, usage | `routes.list()`, `jobs.list()`, `monitors.list()`, `usage.get()` |
| Device environment | `devices.set_environment()`, `devices.delete_environment_variable()` |

The named operations do not yet wrap every operation in Blues' API specification. Use `client.request(method, path, ...)` for other documented endpoints beneath `/v1/`; pass a relative path such as `projects/app:your-project-uid/fleets`. It returns `JSONValue` (a recursive JSON type) or `None` for an empty response. Named read methods return `TypedDict` contracts from `notehub_client.typing` and validate the response envelope before returning it.

## Reusable helpers

The supported helpers live in `notehub_client.helpers`; import the helper module from the package root. They can help when implementing custom operations with `client.request`:

```python
from notehub_client import filters, helpers

path = helpers.encode_path_segments("projects", project_uid, "devices", device_uid)
params = filters.page(page_size=100).to_query_params()
payload = await client.request("GET", path, params=params)
```

| Helper | Behavior |
| --- | --- |
| `validate_bearer_token(value)` | Returns a valid Bearer token or raises `ValueError`. |
| `encode_path_segments(*segments)` | Encodes identifiers as path segments; empty and dot segments raise `ValueError`. |

| `validate_json_value(payload, context="response")` | Validates recursive JSON values and finite numbers; malformed values raise `errors.NotehubResponseError`. |
| `require_json_object(payload, context)` | Requires a JSON object. |
| `require_collection(payload, key, *, paginated=False, optional=False)` | Validates a collection envelope and optional pagination fields. |
| `require_device_collection(payload, *, paginated=True)` | Validates a device collection, including each device's string `uid`. |

The response helpers raise `errors.NotehubResponseError` for malformed data. Type aliases and response shapes used by these helpers are available from `notehub_client.typing`.

Notes and environment-variable writes report whether Notehub accepted the API request. They do not confirm that a device has synchronized or applied the change; device connectivity and synchronization schedules affect when that happens.

## Errors, rate limits, and request behavior

The client raises `errors.NotehubAuthenticationError`, `errors.NotehubPermissionError`, and `errors.NotehubRateLimitError` for HTTP 401, 403, and 429 responses. Other non-success responses use `errors.NotehubAPIError`; inspect `status_code` and `retry_after`. Transport failures raise `errors.NotehubTransportError`, and malformed success responses raise `errors.NotehubResponseError`. Raw response bodies and transport details are not included in exception messages, which avoids leaking credentials or application data.

Requests have a 30-second default timeout, do not follow redirects, and are never retried automatically. Implement retry and backoff at the call site, honoring `Retry-After` for rate limits. Each page is a separate API request. Notehub's free API request threshold is shared across projects on a billing account, so account for other clients when setting polling frequency. Check Blues' current [Notehub API reference](https://dev.blues.io/api-reference/notehub-api/) for permissions and request limits.

## Command line scaffold

Install `pip install "notehub-client[cli]"` to use the `notehub` console script, `notehub-client cli`, or `python -m notehub_client.runtimes.cli`. The Click group is intentionally an empty scaffold; CLI commands will be designed separately. Rich is included for future terminal output.

The `notehub-client` dispatcher accepts a runtime name before its arguments. Install `pip install "notehub-client[tui]"` to add Textual and the CLI dependencies, then start the TUI with `notehub-client tui` or `notehub-client-tui`. The TUI runtime is scaffolded but does not yet provide an interface. Missing optional dependencies produce an install hint for the corresponding extra. The base library does not import runtime dependencies unless a runtime is started.

## Development

```console
just install
just check
just build
```

Tooling is split into `dev`, `lint`, `test`, and `type` uv dependency groups. The `type` group includes `test` because Pyrefly checks both `src` and `tests`. `just prek` runs the configured file hygiene, lint, format, and type hooks across the repository.

The library is unofficial and is not affiliated with or endorsed by Blues Inc. Named operation coverage is partial and follows Blues' evolving [Notehub API documentation](https://dev.blues.io/api-reference/notehub-api/); the generic request method provides access to additional endpoints without waiting for a wrapper.
