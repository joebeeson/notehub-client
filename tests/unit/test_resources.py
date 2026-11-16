import httpx
import pytest
import respx

from notehub_client import NotehubClient
from notehub_client.errors import NotehubResponseError
from notehub_client.filters import BalanceHistoryFilters


@pytest.mark.asyncio
@respx.mock
async def test_billing_account_operations_use_documented_paths_and_shapes() -> None:
    accounts = respx.get("https://api.notefile.net/v1/billing-accounts").mock(
        return_value=httpx.Response(
            200,
            json={
                "billing_accounts": [
                    {"uid": "billing:one", "name": "Main", "role": "billing_admin"}
                ]
            },
        )
    )
    detail = respx.get("https://api.notefile.net/v1/billing-accounts/billing:one").mock(
        return_value=httpx.Response(
            200,
            json={"uid": "billing:one", "name": "Main", "plan": {"current_balance": 42}},
        )
    )
    history = respx.get(
        "https://api.notefile.net/v1/billing-accounts/billing:one/balance-history"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "period": "2026-11-01T00:00:00Z",
                        "remaining_event_capacity": 42,
                        "total_event_capacity_used": 8,
                    }
                ]
            },
        )
    )

    async with NotehubClient("pat") as client:
        assert (await client.billing_accounts.list())["billing_accounts"][0]["uid"] == (
            "billing:one"
        )
        assert (await client.billing_accounts.get("billing:one"))["plan"]["current_balance"] == 42
        result = await client.billing_accounts.balance_history(
            "billing:one", filters=BalanceHistoryFilters(start_date=100, end_date=200)
        )

    assert result["data"][0]["total_event_capacity_used"] == 8
    assert accounts.called and detail.called and history.called
    assert dict(history.calls[0].request.url.params) == {
        "startDate": "100",
        "endDate": "200",
    }


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("collection", "path"),
    [
        pytest.param("billing_accounts", "billing-accounts", id="billing-accounts"),
        pytest.param("organizations", "organizations", id="organizations"),
        pytest.param("projects", "projects", id="projects"),
    ],
)
async def test_optional_collection_fields_are_preserved_when_notehub_omits_them(
    collection: str, path: str
) -> None:
    route = respx.get(f"https://api.notefile.net/v1/{path}").mock(
        return_value=httpx.Response(200, json={})
    )
    async with NotehubClient("pat") as client:
        assert await getattr(client, collection).list() == {}

    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_organization_details_and_balance_history_are_typed_reads() -> None:
    detail = respx.get("https://api.notefile.net/v1/organizations/org:one").mock(
        return_value=httpx.Response(200, json={"uid": "org:one", "name": "Organization"})
    )
    history = respx.get("https://api.notefile.net/v1/organizations/org:one/balance-history").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    async with NotehubClient("pat") as client:
        organization = await client.organizations.get("org:one")
        account_history = await client.organizations.balance_history("org:one")

    assert organization["uid"] == "org:one"
    assert account_history == {"data": []}
    assert detail.called and history.called


@pytest.mark.asyncio
@respx.mock
async def test_fleet_route_job_monitor_and_usage_read_wrappers() -> None:
    fleet_list = respx.get("https://api.notefile.net/v1/projects/app:test/fleets").mock(
        return_value=httpx.Response(200, json={"fleets": []})
    )
    fleet_devices = respx.get(
        "https://api.notefile.net/v1/projects/app:test/fleets/fleet:one/devices"
    ).mock(return_value=httpx.Response(200, json={"devices": [], "has_more": False}))
    fleet_events = respx.get(
        "https://api.notefile.net/v1/projects/app:test/fleets/fleet:one/events"
    ).mock(return_value=httpx.Response(200, json={"events": [], "has_more": False}))
    routes = respx.get("https://api.notefile.net/v1/projects/app:test/routes").mock(
        return_value=httpx.Response(200, json=[])
    )
    jobs = respx.get("https://api.notefile.net/v1/projects/app:test/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": []})
    )
    monitors = respx.get("https://api.notefile.net/v1/projects/app:test/monitors").mock(
        return_value=httpx.Response(200, json=[])
    )
    usage = respx.get("https://api.notefile.net/v1/projects/app:test/usage/api").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    async with NotehubClient("pat") as client:
        assert await client.fleets.list("app:test") == {"fleets": []}
        assert await client.devices.list_for_fleet("app:test", "fleet:one") == {
            "devices": [],
            "has_more": False,
        }
        assert await client.events.list_for_fleet("app:test", "fleet:one") == {
            "events": [],
            "has_more": False,
        }
        assert await client.routes.list("app:test") == []
        assert await client.jobs.list("app:test") == {"jobs": []}
        assert await client.monitors.list("app:test") == []
        assert await client.usage.get("app:test") == {"data": []}

    assert all(
        route.called
        for route in (fleet_list, fleet_devices, fleet_events, routes, jobs, monitors, usage)
    )


@pytest.mark.asyncio
@respx.mock
async def test_device_resource_reads_return_typed_envelopes() -> None:
    device = respx.get("https://api.notefile.net/v1/projects/app:test/devices/dev:one").mock(
        return_value=httpx.Response(
            200,
            json={
                "uid": "dev:one",
                "product_uid": "product:example:project",
                "provisioned": "2026-11-01T00:00:00Z",
                "fleet_uids": [],
                "temperature": 21.5,
                "voltage": 5.0,
            },
        )
    )
    sessions = respx.get(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:one/sessions"
    ).mock(return_value=httpx.Response(200, json={"sessions": [], "has_more": False}))
    latest = respx.get("https://api.notefile.net/v1/projects/app:test/devices/dev:one/latest").mock(
        return_value=httpx.Response(200, json={})
    )
    environment = respx.get(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:one/environment_variables"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "environment_variables": {},
                "environment_variables_env_default": {},
            },
        )
    )

    async with NotehubClient("pat") as client:
        assert (await client.devices.get("app:test", "dev:one"))["uid"] == "dev:one"
        assert await client.devices.list_sessions("app:test", "dev:one") == {
            "sessions": [],
            "has_more": False,
        }
        assert await client.devices.latest("app:test", "dev:one") == {}
        assert await client.devices.get_environment("app:test", "dev:one") == {
            "environment_variables": {},
            "environment_variables_env_default": {},
        }

    assert all(route.called for route in (device, sessions, latest, environment))


@pytest.mark.asyncio
@respx.mock
async def test_device_collection_rejects_empty_pages_claiming_more_results() -> None:
    route = respx.get("https://api.notefile.net/v1/projects/app:test/devices").mock(
        return_value=httpx.Response(200, json={"devices": [], "has_more": True})
    )
    async with NotehubClient("pat") as client:
        with pytest.raises(NotehubResponseError, match="Empty device page"):
            await client.devices.collect("app:test")
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_device_details_require_a_string_uid() -> None:
    route = respx.get("https://api.notefile.net/v1/projects/app:test/devices/dev:missing").mock(
        return_value=httpx.Response(200, json={"name": "missing uid"})
    )
    async with NotehubClient("pat") as client:
        with pytest.raises(NotehubResponseError, match="missing a string uid"):
            await client.devices.get("app:test", "dev:missing")
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_event_collect_returns_items_from_the_cursor_iterator() -> None:
    route = respx.get("https://api.notefile.net/v1/projects/app:test/events").mock(
        return_value=httpx.Response(
            200,
            json={"events": [{"event": "first"}], "has_more": False},
        )
    )
    async with NotehubClient("pat") as client:
        assert await client.events.collect("app:test") == [{"event": "first"}]
    assert route.called


@pytest.mark.parametrize(
    ("resource", "path"),
    [
        pytest.param("routes", "routes", id="routes"),
        pytest.param("monitors", "monitors", id="monitors"),
    ],
)
@pytest.mark.asyncio
@respx.mock
async def test_route_and_monitor_lists_reject_non_collection_responses(
    resource: str, path: str
) -> None:
    route = respx.get(f"https://api.notefile.net/v1/projects/app:test/{path}").mock(
        return_value=httpx.Response(200, json={"unexpected": []})
    )
    async with NotehubClient("pat") as client:
        with pytest.raises(NotehubResponseError, match=f"list_{resource}"):
            await getattr(client, resource).list("app:test")
    assert route.called
