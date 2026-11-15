# notehub-client

An unofficial asynchronous Python client for the Blues Notehub REST API.

## Install

The package is being prepared for PyPI. Until publication, install from GitHub:

```console
pip install "notehub-client @ git+https://github.com/joebeeson/notehub-client.git"
```

Create a Personal Access Token in Notehub API Access settings and store it in your application's secret manager. Blues recommends PATs for new API clients. OAuth client credentials are supported with the optional `oauth` extra.

## Quick start

```python
import asyncio
import os
from notehub_client import NotehubClient

async def main():
    async with NotehubClient(os.environ["NOTEHUB_TOKEN"]) as client:
        devices = await client.get_devices("app:your-project-uid")
        async for event in client.iter_project_events("app:your-project-uid"):
            print(event.get("device"), event.get("file"), event.get("body"))

asyncio.run(main())
```

The client owns its HTTPX pool when it creates it. Pass `http_client=httpx.AsyncClient(...)` to reuse a configured client; supplied clients remain caller-owned.

## OAuth

Install `pip install "notehub-client[oauth]"`, then pass `NotehubOAuthTokenProvider(client_id, client_secret)` as `token_provider`. It obtains project-scoped client-credentials tokens and renews them before their 30-minute expiry. Keep the provider alive with the API client and close it with `await provider.aclose()` when done. Notehub does not issue a refresh token for this grant. PATs remain Blues' recommended authentication for new integrations. See the [authorization API](https://dev.blues.io/api-reference/notehub-api/authorization-api/).

## API and pagination

Convenience methods cover project and device discovery, project events, device Notes, and environment variables. `client.resources` provides named entry points for fleets, sessions, routes, jobs, monitors, organization listing, and usage. `client.request(method, path, ...)` supports any documented endpoint beneath `/v1/` and returns decoded JSON (or `None` for empty responses). Notehub response payloads are dictionaries to preserve optional and evolving fields.

Use `iter_devices` and `iter_project_events` to stream paginated results. Event iteration starts at cursor `0` by default. Pass a saved cursor to resume; page-level event responses include Notehub's `next_cursor`. An invalid or non-advancing cursor raises `NotehubAPIError` when more results are claimed.

API errors expose `status_code`, response `payload`, and `retry_after`. Authentication, permission, and rate limit errors have dedicated subclasses. Transport errors are raised separately. Writes are never retried automatically.

Review Blues' [API documentation](https://dev.blues.io/api-reference/notehub-api/) for current permissions and rate limits. Request allowances are shared across a billing account.

## Command line

Install `pip install "notehub-client[cli]"` to add the `notehub` entry point or run `python -m notehub_client`. The Click command group is an empty scaffold; commands will be designed after the library API settles. Rich is included for future terminal output.

## Development

```console
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run mypy src
uv build
```

This project is unofficial and is not affiliated with or endorsed by Blues Inc. API coverage follows Blues' [Notehub API reference](https://dev.blues.io/api-reference/notehub-api/).
