import json

import httpx
import pytest
import respx

from notehub_client import NotehubClient
from notehub_client.compose import Composer
from notehub_client.errors import NotehubResponseError
from notehub_client.filters import BalanceHistoryFilters, cursor, page
from notehub_client.typing import JSONValue


@pytest.mark.asyncio
@respx.mock
async def test_session_pages_resume_after_terminal_checkpoint_to_read_updates() -> None:
    route = respx.get("https://api.notefile.net/v1/projects/app:test/devices/dev:one/sessions")
    opened = {"session": "same-session", "session_began": 100}
    closed = {**opened, "session_ended": 105}
    route.mock(
        side_effect=[
            httpx.Response(
                200, json={"sessions": [opened], "has_more": True, "next_cursor": "more"}
            ),
            httpx.Response(
                200, json={"sessions": [], "has_more": False, "next_cursor": "caught-up"}
            ),
            httpx.Response(
                200, json={"sessions": [closed], "has_more": False, "next_cursor": "end"}
            ),
        ]
    )
    async with NotehubClient("pat") as client:
        pages = [
            result
            async for result in client.devices.iter_session_pages(
                "app:test", "dev:one", pagination=cursor(page_size=2), startDate=90
            )
        ]
        assert [result["sessions"] for result in pages] == [[opened], []]
        resumed = [
            result
            async for result in client.devices.iter_session_pages(
                "app:test",
                "dev:one",
                pagination=cursor(pages[-1]["next_cursor"], page_size=2),
                startDate=90,
            )
        ]
        assert resumed[0]["sessions"] == [closed]
    assert [dict(call.request.url.params) for call in route.calls] == [
        {"pageSize": "2", "startDate": "90", "cursor": checkpoint}
        for checkpoint in ("0", "more", "caught-up")
    ]


@pytest.mark.asyncio
@respx.mock
async def test_session_pagination_rejects_mixed_modes_and_stalled_continuation() -> None:
    route = respx.get("https://api.notefile.net/v1/projects/app:test/devices/dev:one/sessions")
    route.mock(
        return_value=httpx.Response(
            200, json={"sessions": [], "has_more": True, "next_cursor": "0"}
        )
    )
    async with NotehubClient("pat") as client:
        with pytest.raises(ValueError, match="cursor cannot be combined with pageNum"):
            await client.devices.list_sessions(
                "app:test", "dev:one", pagination=page(page_num=1), cursor="0"
            )
        assert not route.called
        with pytest.raises(NotehubResponseError, match="Session cursor missing or repeated"):
            await anext(client.devices.iter_session_pages("app:test", "dev:one"))


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        pytest.param("project", {"label": "Missing UID"}, id="project-without-uid"),
        pytest.param("projects", {"projects": [{"uid": 123}]}, id="project-with-numeric-uid"),
        pytest.param("fleets", {"fleets": [{"uid": ""}]}, id="fleet-with-empty-uid"),
    ],
)
@pytest.mark.asyncio
@respx.mock
async def test_inventory_reads_reject_records_without_usable_uids(
    endpoint: str, payload: JSONValue
) -> None:
    suffix = {
        "project": "projects/app:test",
        "projects": "projects",
        "fleets": "projects/app:test/fleets",
    }
    route = respx.get(f"https://api.notefile.net/v1/{suffix[endpoint]}").mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with NotehubClient("pat") as client:
        with pytest.raises(NotehubResponseError, match="string uid"):
            if endpoint == "project":
                await client.projects.get("app:test")
            elif endpoint == "projects":
                await client.projects.list()
            else:
                await client.fleets.list("app:test")
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_environment_edit_adapts_update_once_and_skips_noop() -> None:
    path = "https://api.notefile.net/v1/projects/app:test/devices/dev:one/environment_variables"
    read = respx.get(path).mock(
        return_value=httpx.Response(
            200, json={"environment_variables": {"mode": "quiet", "keep": "same", "remove": "old"}}
        )
    )
    write = respx.put(path).mock(return_value=httpx.Response(204))
    delete = respx.delete(f"{path}/remove").mock(return_value=httpx.Response(204))
    composer = Composer()
    conversions: list[str] = []

    @composer.environment_value.register(str)
    def adapt(value: str) -> str:
        conversions.append(value)
        return f"adapted:{value}"

    async with NotehubClient("pat", composer=composer) as client:
        environment = client.devices["app:test", "dev:one"].environment
        async with environment.edit():
            pass
        assert not write.called and not delete.called
        async with environment.edit() as values:
            values["mode"] = "active"
            del values["remove"]

    assert read.call_count == 2
    assert write.call_count == 1
    assert delete.call_count == 1
    assert conversions == ["active"]
    assert json.loads(write.calls[0].request.content) == {
        "environment_variables": {"mode": "adapted:active"}
    }


@pytest.mark.asyncio
@respx.mock
async def test_environment_edit_validates_delete_path_before_update() -> None:
    path = "https://api.notefile.net/v1/projects/app:test/devices/dev:one/environment_variables"
    respx.get(path).mock(
        return_value=httpx.Response(200, json={"environment_variables": {"legacy": "old"}})
    )
    composer = Composer()

    @composer.notehub_identifier.register(str)
    def adapt(value: str) -> str:
        return ".." if value == "legacy" else value

    async with NotehubClient("pat", composer=composer) as client:
        environment = client.devices["app:test", "dev:one"].environment
        with pytest.raises(ValueError, match="dot segments"):
            async with environment.edit() as values:
                del values["legacy"]
                values["mode"] = "active"
    assert [call.request.method for call in respx.calls] == ["GET"]


@pytest.mark.parametrize(
    "field",
    [
        "environment_variables",
        "environment_variables_env_default",
        "environment_variables_effective",
        "environment_variable_notes",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="null"),
        pytest.param([], id="array"),
        pytest.param("private-value", id="scalar"),
        pytest.param({"secret": 42}, id="non-string-value"),
        pytest.param({"secret": {"private-value": "hidden"}}, id="nested-value"),
    ],
)
@respx.mock
@pytest.mark.asyncio
async def test_environment_response_rejects_malformed_mappings_before_edit(
    field: str,
    value: JSONValue,
) -> None:
    payload: dict[str, JSONValue] = {"environment_variables": {}}
    payload[field] = value
    route = respx.get(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:one/environment_variables"
    ).mock(return_value=httpx.Response(200, json=payload))
    async with NotehubClient("pat") as client:
        with pytest.raises(NotehubResponseError, match=f"string mapping for {field}") as caught:
            async with client.devices["app:test", "dev:one"].environment.edit():
                pytest.fail("Malformed environment must fail before editing begins")
    assert "private-value" not in str(caught.value)
    assert "secret" not in str(caught.value)
    assert route.call_count == 1
    assert len(respx.calls) == 1


@respx.mock
@pytest.mark.asyncio
async def test_environment_response_requires_device_values() -> None:
    respx.get(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:one/environment_variables"
    ).mock(return_value=httpx.Response(200, json={"environment_variables_effective": {}}))
    async with NotehubClient("pat") as client:
        with pytest.raises(NotehubResponseError, match="Missing environment_variables"):
            await client.devices["app:test", "dev:one"].environment.read()


@respx.mock
@pytest.mark.asyncio
async def test_environment_read_copies_device_values_and_preserves_response_extensions() -> None:
    payload = {
        "environment_variables": {"mode": "quiet"},
        "environment_variables_env_default": {"mode": "default"},
        "environment_variables_effective": {"mode": "quiet", "inherited": "yes"},
        "environment_variable_notes": {"mode": "description"},
        "future_field": {"anything": True},
    }
    respx.get(
        "https://api.notefile.net/v1/projects/app:test/devices/dev:one/environment_variables"
    ).mock(return_value=httpx.Response(200, json=payload))
    async with NotehubClient("pat") as client:
        assert await client.devices.get_environment("app:test", "dev:one") == payload
        environment = client.devices["app:test", "dev:one"].environment
        values = await environment.read()
        assert values == {"mode": "quiet"}
        values["mode"] = "changed"
        assert await environment.read() == {"mode": "quiet"}


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
    ).mock(
        return_value=httpx.Response(
            200, json={"sessions": [], "has_more": False, "next_cursor": "terminal"}
        )
    )
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
        assert await client.devices.list_sessions("app:test", "dev:one", cursor="0") == {
            "sessions": [],
            "has_more": False,
            "next_cursor": "terminal",
        }
        assert await client.devices.latest("app:test", "dev:one") == {}
        assert await client.devices.get_environment("app:test", "dev:one") == {
            "environment_variables": {},
            "environment_variables_env_default": {},
        }

    assert all(route.called for route in (device, sessions, latest, environment))
    assert sessions.calls.last.request.url.params["cursor"] == "0"


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
