import httpx
import pytest
import respx

from notehub_client.client import NotehubClient
from notehub_client.errors import NotehubPermissionError, NotehubResponseError
from notehub_client.filters import Query
from notehub_client.runtimes.tui.demo import DEMO_DEVICE_UID, DEMO_PROJECT_UID, DemoReadService
from notehub_client.runtimes.tui.paging import CursorHistory
from notehub_client.runtimes.tui.service import TUIReadService, adapt_page


@pytest.mark.asyncio
async def test_service_uses_one_bounded_cursor_read_and_preserves_client_ownership() -> None:
    with respx.mock as router:
        endpoint = router.get("https://api.notefile.net/v1/projects/app:test/events").mock(
            return_value=httpx.Response(
                200, json={"events": [{"event": "e1"}], "has_more": True, "next_cursor": "next"}
            )
        )
        async with NotehubClient("test-token") as client:
            service = TUIReadService(client)
            page = await service.read(
                "events", project_uid="app:test", query=Query().devices("dev:one")
            )
            assert page.row_keys == ("e1",)
            assert page.next_cursor == "next"
            request = endpoint.calls[0].request
            assert request.url.params["cursor"] == "0"
            assert request.url.params["pageSize"] == "50"
            assert request.url.params["deviceUID"] == "dev:one"
            assert len(endpoint.calls) == 1


@pytest.mark.asyncio
async def test_service_preserves_permission_error_for_view_recovery() -> None:
    with respx.mock as router:
        router.get("https://api.notefile.net/v1/projects/app:test/routes").mock(
            return_value=httpx.Response(403, json={"err": "private response"})
        )
        async with NotehubClient("test-token") as client:
            with pytest.raises(NotehubPermissionError):
                await TUIReadService(client).read("routes", project_uid="app:test")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "uid", "url"),
    [
        (
            "organization_history",
            "org:one",
            "https://api.notefile.net/v1/organizations/org:one/balance-history",
        ),
        (
            "billing_history",
            "bill:one",
            "https://api.notefile.net/v1/billing-accounts/bill:one/balance-history",
        ),
    ],
)
async def test_balance_history_adapts_query_dates_to_typed_filters(
    operation: str, uid: str, url: str
) -> None:
    with respx.mock as router:
        endpoint = router.get(url).mock(return_value=httpx.Response(200, json={"data": []}))
        async with NotehubClient("test-token") as client:
            await TUIReadService(client).read(
                operation, uid=uid, query=Query().date_range(100, 200)
            )
        assert dict(endpoint.calls[0].request.url.params) == {"startDate": "100", "endDate": "200"}


def test_environment_adapter_discards_values_before_copy_export_or_cache() -> None:
    page = adapt_page(
        "environment",
        {
            "environment_variables": {"SECRET": "sensitive"},
            "environment_variables_effective": {"SECRET": "sensitive"},
            "environment_variable_notes": {"SECRET": "sensitive note"},
        },
    )
    assert len(page.rows) == 2
    assert all(row["value"] == "[masked]" for row in page.rows)
    assert "sensitive" not in repr(page)


def test_row_keys_handle_missing_duplicate_and_suffixed_real_ids() -> None:
    rows = [{"event": "a"}, {"event": "a"}, {"event": "a#1"}, {}, {}]
    page = adapt_page("events", {"events": rows, "has_more": False})
    assert len(set(page.row_keys)) == 5
    assert "event" not in page.rows[3]
    rows[0]["event"] = "changed"
    assert page.rows[0]["event"] == "a"


@pytest.mark.parametrize("next_cursor", [None, "", "0"], ids=["missing", "empty", "same"])
def test_cursor_validation_stops_invalid_continuation(next_cursor: str | None) -> None:
    envelope = {"events": [], "has_more": True}
    if next_cursor is not None:
        envelope["next_cursor"] = next_cursor
    with pytest.raises(NotehubResponseError, match="cursor"):
        adapt_page("events", envelope)


def test_cursor_history_bounds_snapshots_and_rejects_multi_page_cycle() -> None:
    pager = CursorHistory(capacity=2)
    first = adapt_page("events", {"events": [], "has_more": True, "next_cursor": "a"})
    second = adapt_page("events", {"events": [], "has_more": True, "next_cursor": "b"}, cursor="a")
    third = adapt_page("events", {"events": [], "has_more": True, "next_cursor": "c"}, cursor="b")
    pager.append("0", first)
    pager.append("a", second)
    pager.append("b", third)
    assert pager.previous() == second
    assert not pager.can_previous
    assert pager.forward() == third
    cycle = adapt_page("events", {"events": [], "has_more": True, "next_cursor": "b"}, cursor="c")
    with pytest.raises(NotehubResponseError, match="cursor"):
        pager.append("c", cycle)
    assert pager.current == third
    pager.reset()
    assert pager.current is None
    assert pager.next_cursor == "0"


@pytest.mark.asyncio
async def test_demo_has_multiple_pages_and_filters_without_network() -> None:
    demo = DemoReadService()
    first = await demo.read("events", project_uid=DEMO_PROJECT_UID)
    second = await demo.read("events", project_uid=DEMO_PROJECT_UID, cursor=first.next_cursor or "")
    third = await demo.read("events", project_uid=DEMO_PROJECT_UID, cursor=second.next_cursor or "")
    assert [len(page.rows) for page in (first, second, third)] == [50, 50, 37]
    assert third.has_more is False
    filtered = await demo.read(
        "events",
        project_uid=DEMO_PROJECT_UID,
        query=Query().devices(DEMO_DEVICE_UID).files("sensors.qo"),
    )
    assert all(
        row["device"] == DEMO_DEVICE_UID and row["file"] == "sensors.qo" for row in filtered.rows
    )
    demo.fail_next("events", NotehubPermissionError(403, "denied"))
    with pytest.raises(NotehubPermissionError):
        await demo.read("events", project_uid=DEMO_PROJECT_UID)
    assert (await demo.read("events", project_uid=DEMO_PROJECT_UID)).rows


@pytest.mark.asyncio
async def test_demo_rejects_non_string_selector_filter_values() -> None:
    query = Query.from_value({"deviceUID": True})
    with pytest.raises(ValueError, match="selector filters must contain strings"):
        await DemoReadService().read("events", project_uid=DEMO_PROJECT_UID, query=query)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    [
        "project",
        "devices",
        "device",
        "latest",
        "sessions",
        "environment",
        "fleets",
        "fleet_devices",
        "fleet_events",
        "routes",
        "jobs",
        "monitors",
        "usage",
        "organizations",
        "organization",
        "organization_history",
        "billing_accounts",
        "billing_account",
        "billing_history",
    ],
)
async def test_demo_covers_every_destination(operation: str) -> None:
    page = await DemoReadService().read(
        operation, project_uid=DEMO_PROJECT_UID, uid=DEMO_DEVICE_UID
    )
    assert page.rows
