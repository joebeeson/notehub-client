from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from notehub_client import NotehubClient, compose, filters, simulate
from notehub_client.errors import NotehubAPIError, NotehubRateLimitError, NotehubTransportError
from notehub_client.observe import RequestFailed, RequestFinished, RequestStarted
from notehub_client.simulate.converters import resolve_scenario, scenario_value
from notehub_client.typing import ScenarioSource

P, D = "app:demo", "dev:temperature"


@pytest.mark.asyncio
async def test_toml_queued_work_and_existing_history(datadir: Path) -> None:
    scenario = simulate.Scenario.from_toml(datadir / "sensor.toml")
    with scenario.start() as run:
        device = run.device(P, D)
        async with run.client() as client:
            assert (await client.projects.list())["projects"][0]["uid"] == P
            assert len(await client.events.collect(P)) == 1
            device.queue_many("temperature.qo", ({"celsius": n} for n in (20, 21)))
            run.advance(timedelta(minutes=1))
            result = device.sync()
            assert (result.sent, result.received) == (3, 1)
            found = await client.events.collect(
                P,
                filters=filters.devices(D).files("temperature.qo"),
                pagination=filters.CursorPagination(page_size=1),
            )
            assert [event["body"]["celsius"] for event in found] == [19, 18, 20, 21]
            assert found[-1]["received"] - found[-1]["when"] == 60
            device.sync()
            assert len(await client.events.collect(P)) == 4
            await client.notes.add_qi(device.note("commands.qi"), {"action": "sample"})
            wake = device.receive("commands.qi")
            assert wake is not None and wake["body"] == {"action": "wake"}
            assert device.receive("commands.qi") is None
            device.sync()
            peek = device.receive("commands.qi", delete=False)
            assert peek is not None and peek["body"] == {"action": "sample"}
            consumed = device.receive("commands.qi")
            assert consumed is not None and consumed["body"] == {"action": "sample"}
            assert device.receive("commands.qi") is None
            assert len((await client.devices.list_sessions(P, D))["sessions"]) == 3
            assert len((await client.devices.latest(P, D))["latest_events"]) == 1


@pytest.mark.parametrize("name", simulate.available())
def test_named_assets_and_runs_are_independent(name: str) -> None:
    first = simulate.named(name)
    assert first == simulate.Scenario.named(name)
    project_uid = first.projects[0].uid
    device_uid = first.devices[0].uid
    with first.start() as a, first.start() as b:
        before = b.snapshot()
        a.device(project_uid, device_uid).queue("test.qo", {"nested": [1, None, {"value": True}]})
        assert b.snapshot() == before
        a.device(project_uid, device_uid).sync()
        assert a.snapshot() != before
        snap = a.snapshot()
        with pytest.raises(TypeError):
            snap["events"][0]["body"]["changed"] = True
    with pytest.raises(RuntimeError, match="closed"):
        a.advance(timedelta(seconds=1))


def test_field_lab_preset_has_a_narrative_multi_device_workflow() -> None:
    scenario = simulate.named("field_lab")

    assert len(scenario.projects) == 1
    assert len(scenario.fleets) == 2
    assert len(scenario.devices) == 3
    assert len(scenario.events) >= 3
    assert len(scenario.outbound) >= 2
    assert len(scenario.inbound) >= 2
    assert len(scenario.behaviors) == 3

    with scenario.start(seed=73) as run:
        first = run.step()
        assert len(first) == 3
        first_device_key = (scenario.devices[0].project_uid, scenario.devices[0].uid)
        assert run.snapshot()["devices"][first_device_key]["steps"] == 1


def test_fluent_python_and_toml_share_models() -> None:
    python = (
        simulate.Scenario()
        .with_project(P)
        .with_device(P, D)
        .with_inbound(P, D, "commands.qi", {"action": "sample", "count": 5})
        .with_inbound(P, D, "commands.qi", {"action": "wake"}, delivered=True)
    )
    assert python == simulate.named("commands")
    assert not simulate.Scenario().projects
    with pytest.raises(FrozenInstanceError):
        setattr(python, "start_time", datetime.now(timezone.utc))
    body = {"nested": [1]}
    queued = simulate.QueuedNote(P, D, "data.qo", body)
    body["nested"].append(2)
    assert queued.body["nested"] == (1,)


def test_structural_sources_and_public_converter_registration() -> None:
    class Source:
        def to_scenario(self) -> simulate.Scenario:
            return simulate.named("commands")

    source: ScenarioSource = Source()
    assert simulate.Scenario.from_value(source) == simulate.named("commands")

    class Foreign:
        pass

    @scenario_value.register(Foreign)
    def convert(value: Foreign) -> object:
        return simulate.named("telemetry")

    assert resolve_scenario(Foreign()) == simulate.named("telemetry")
    assert resolve_scenario({"scenario_version": 1}) == simulate.Scenario()
    with pytest.raises(TypeError):
        resolve_scenario("telemetry")

    class Invalid:
        def to_scenario(self):
            return None

    with pytest.raises(TypeError, match="converter"):
        resolve_scenario(Invalid())


@pytest.mark.asyncio
async def test_environment_hierarchy_and_sync_visibility() -> None:
    with simulate.named("environment").start() as run:
        device = run.device(P, D)
        assert device.environment == {"SAMPLE_INTERVAL": "900", "FORMAT": "celsius"}
        async with run.client() as client:
            device.sync()
            assert device.environment["SAMPLE_INTERVAL"] == "10"
            assert device.environment["REGION"] == "global"
            await client.devices.delete_environment_variable(device, "SAMPLE_INTERVAL")
            effective = await client.devices.get_environment(device)
            assert effective["environment_variables"] == {}
            # Fleet alpha wins although its UID sorts after Zulu's UID.
            assert effective["environment_variables_effective"]["SAMPLE_INTERVAL"] == "60"
            assert device.environment["SAMPLE_INTERVAL"] == "10"
            device.sync()
            assert device.environment["SAMPLE_INTERVAL"] == "60"
            await client.request(
                "DELETE", f"projects/{P}/fleets/fleet:z/environment_variables/SAMPLE_INTERVAL"
            )
            device.sync()
            assert device.environment["SAMPLE_INTERVAL"] == "120"
            await client.request(
                "DELETE", f"projects/{P}/fleets/fleet:a/environment_variables/SAMPLE_INTERVAL"
            )
            device.sync()
            assert device.environment["SAMPLE_INTERVAL"] == "300"
            await client.request("DELETE", f"projects/{P}/environment_variables/SAMPLE_INTERVAL")
            device.sync()
            assert device.environment["SAMPLE_INTERVAL"] == "900"
            await client.devices.set_environment(device, {"SAMPLE_INTERVAL": "5"})
            device.sync()
            assert device.environment["SAMPLE_INTERVAL"] == "5"


@pytest.mark.asyncio
async def test_query_filters_pagination_projection_and_cursor_scoping() -> None:
    definition = (
        simulate.Scenario()
        .with_project(P)
        .with_fleet(P, "fleet:one")
        .with_device(P, D, fleet_uids=("fleet:one",), serial_number="SN1")
        .with_device(P, "dev:other")
    )
    with definition.start() as run:
        device = run.device(P, D)
        device.queue_many("data.qo", ({"i": i} for i in range(5)))
        device.sync()
        async with run.client() as client:
            assert (
                len(await client.devices.collect(P, pagination=filters.Pagination(page_size=1)))
                == 2
            )
            assert len((await client.devices.list_for_fleet(P, "fleet:one"))["devices"]) == 1
            assert len((await client.fleets.list(P))["fleets"]) == 1
            page = await client.events.list(P, pagination=filters.CursorPagination(page_size=2))
            cursor = page["next_cursor"]
            more = await client.events.list(
                P, pagination=filters.CursorPagination(cursor=cursor, page_size=2)
            )
            assert more["events"][0]["body"] == {"i": 2}
            with pytest.raises(NotehubAPIError) as error:
                await client.events.list(
                    P,
                    filters=filters.files("other.qo"),
                    pagination=filters.CursorPagination(cursor=cursor, page_size=2),
                )
            assert error.value.status_code == 400
            with definition.start() as other:
                async with other.client() as other_client:
                    with pytest.raises(NotehubAPIError):
                        await other_client.events.list(
                            P, pagination=filters.CursorPagination(cursor=cursor, page_size=2)
                        )
            selected = await client.events.list(
                P,
                deviceUID=(D, "missing"),
                files="data.qo,other.qo",
                serialNumber="SN1",
                fleetUID="fleet:one",
                selectFields="event,body",
                dateType="uploaded",
                startDate=int(run.now.timestamp()),
                endDate=int(run.now.timestamp()),
            )
            assert len(selected["events"]) == 5
            assert set(selected["events"][0]) == {"event", "body"}
            assert len((await client.events.list_for_fleet(P, "fleet:one"))["events"]) == 5
            event_id = page["events"][0]["event"]
            assert len((await client.events.list(P, eventUID=event_id))["events"]) == 1
            assert len((await client.events.list(P, since=event_id))["events"]) == 4
            assert not (await client.events.list(P, systemFilesOnly=True))["events"]


@pytest.mark.asyncio
async def test_lifecycle_and_shared_clients() -> None:
    run = simulate.named("commands").start()
    device = run.device(P, D)
    with pytest.raises(KeyError):
        run.device("app:wrong", D)
    async with run.client() as first:
        async with run.client() as second:
            await first.notes.add_qi(device.note("commands.qi"), {"extra": True})
            assert device.sync().received == 2
            assert (await second.devices.get(P, D))["uid"] == D
        assert (await first.projects.get(P))["uid"] == P
    with pytest.raises(RuntimeError, match="closed"):
        await first.projects.list()
    async with run.client() as third:
        run.close()
        with pytest.raises(NotehubTransportError):
            await third.projects.list()
    for operation in (
        lambda: device.queue("data.qo", {}),
        device.sync,
        lambda: device.receive("commands.qi"),
        lambda: device.environment,
        run.snapshot,
        run.transport,
    ):
        with pytest.raises(RuntimeError, match="closed"):
            operation()


@pytest.mark.asyncio
async def test_errors_and_observation_stay_on_normal_client_path() -> None:
    run = simulate.named("commands").start()
    observed = []

    class Sink:
        def on_event(self, event):
            observed.append(event)

    async with run.client(observer=Sink()) as client:
        run.fail_next("GET", "projects", status_code=429, retry_after="7")
        with pytest.raises(NotehubRateLimitError) as error:
            await client.projects.list()
        assert error.value.retry_after == "7"
        assert isinstance(observed[0], RequestStarted)
        assert isinstance(observed[1], RequestFinished)
        assert observed[1].status_code == 429
        run.fail_next("GET", "projects", status_code=None)
        with pytest.raises(NotehubTransportError):
            await client.projects.list()
        assert isinstance(observed[-1], RequestFailed)
        assert (await client.projects.list())["projects"]
        for call in (
            lambda: client.routes.list(P),
            lambda: client.events.list(P, unknown="no"),
            lambda: client.notes.add_db(P, D, "state.db", "state", {}),
        ):
            with pytest.raises(NotehubAPIError) as unsupported:
                await call()
            assert unsupported.value.status_code == 501


@pytest.mark.asyncio
async def test_transport_injection_never_uses_network(monkeypatch: pytest.MonkeyPatch) -> None:
    async def network(*_args, **_kwargs):
        pytest.fail("network transport must not be invoked")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", network)
    with simulate.named("commands").start() as run:
        async with httpx.AsyncClient(transport=run.transport()) as http:
            async with NotehubClient("dummy-token", http_client=http) as client:
                assert (await client.devices.get(P, D))["uid"] == D
                with pytest.raises(NotehubAPIError) as error:
                    await client.devices.get("app:missing", D)
                assert error.value.status_code == 404


@pytest.mark.parametrize(
    "data,match",
    [
        ({}, "scenario_version"),
        ({"scenario_version": 2}, "scenario_version"),
        ({"scenario_version": 1, "surprise": True}, "scenario"),
        ({"scenario_version": 1, "devices": [{"project_uid": P, "uid": D}]}, "project"),
        ({"scenario_version": 1, "projects": [{"uid": P}, {"uid": P}]}, "duplicate"),
        (
            {
                "scenario_version": 1,
                "projects": [{"uid": P}],
                "devices": [{"uid": D, "project_uid": P, "fleet_uids": ["absent"]}],
            },
            "fleet",
        ),
        ({"scenario_version": 1, "outbound": [{"device_uid": D}]}, "outbound"),
    ],
)
def test_invalid_scenarios_report_construction_location(data: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        simulate.Scenario.from_mapping(data)


def test_composition_values_and_clock() -> None:
    class Reading:
        def to_note_body(self):
            return {"nested": [True, None, 1.5]}

    with simulate.Scenario().with_project(P).with_device(P, D).start() as run:
        run.device(P, D).queue("data.qo", Reading())
        assert run.snapshot()["devices"][(P, D)]["outbound"][0]["body"]["nested"] == (
            True,
            None,
            1.5,
        )
        with pytest.raises(ValueError):
            run.advance(timedelta(seconds=-1))
        with pytest.raises(ValueError):
            run.device(P, D).queue("bad.db", {})
        assert compose.resolve_target(run.device(P, D)) == compose.DeviceTarget(P, D)
    with pytest.raises(ValueError, match="timezone"):
        simulate.Scenario(start_time=datetime(2025, 1, 1))


def test_reproducible_ids_snapshots_and_partial_generator_failure() -> None:
    scenario = (
        simulate.Scenario()
        .with_project(P)
        .with_device(P, D)
        .with_outbound(P, D, "data.qo", {}, note="sim-note-00000001")
    )

    def readings():
        yield {"i": 1}
        raise ValueError("sensor failure")

    with scenario.start() as a, scenario.start() as b:
        for run in (a, b):
            device = run.device(P, D)
            with pytest.raises(ValueError, match="sensor failure"):
                device.queue_many("data.qo", readings())
            before = run.snapshot()
            device.sync()
            assert len(before["devices"][(P, D)]["outbound"]) == 2
            assert not run.snapshot()["devices"][(P, D)]["outbound"]
        assert a.snapshot() == b.snapshot()
        notes = [e["note"] for e in a.snapshot()["events"]]
        assert len(notes) == len(set(notes))


@pytest.mark.asyncio
async def test_serial_session_sensor_sorting_and_scoped_device_identity() -> None:
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    scenario = (
        simulate.Scenario()
        .with_project(P)
        .with_project("app:second")
        .with_device(P, D)
        .with_device("app:second", D)
        .with_event(
            P,
            D,
            "_health.qo",
            {},
            sensor="sensor:one",
            session="sess:one",
            when=now,
            received=now,
            event="event:one",
        )
        .with_event(
            P,
            D,
            "data.qo",
            {},
            when=now + timedelta(seconds=1),
            received=now + timedelta(seconds=2),
        )
    )
    with scenario.start() as run:
        run.device("app:second", D).queue("isolated.qo", {})
        run.device("app:second", D).sync()
        async with run.client() as client:
            events = await client.events.list(P, sensorUID="sensor:one", sessionUID="sess:one")
            assert len(events["events"]) == 1
            assert len((await client.events.list(P, systemFilesOnly=True))["events"]) == 1
            ordered = await client.events.list(P, sortBy="captured", sortOrder="desc", pageSize=1)
            assert ordered["events"][0]["file"] == "data.qo"
            assert (await client.devices.latest("app:second", D))["latest_events"][0][
                "file"
            ] == "isolated.qo"


@pytest.mark.asyncio
async def test_encoded_identifiers_invalid_requests_and_transport_close() -> None:
    scenario = simulate.Scenario().with_project("app:a/b").with_device("app:a/b", "dev:a/b")
    with scenario.start() as run:
        async with run.client() as client:
            assert (await client.devices.get("app:a/b", "dev:a/b"))["uid"] == "dev:a/b"
        transport = run.transport()
        async with httpx.AsyncClient(
            transport=transport, base_url="https://simulation.invalid"
        ) as http:
            assert (await http.get("/not-v1")).status_code == 501
            assert (await http.get("/v1/projects?pageSize=0")).status_code == 400
            response = await http.put(
                "/v1/projects/app:a%2Fb/environment_variables",
                json={"environment_variables": {"bad": 1}},
            )
            assert response.status_code == 400
            assert run.snapshot()["projects"]["app:a/b"] == {}
            await transport.aclose()
            with pytest.raises(httpx.ConnectError):
                await http.get("/v1/projects")
