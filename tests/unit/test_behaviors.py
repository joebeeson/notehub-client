"""Behavior contracts, plugin discovery, and ordinary-client simulation workflows."""

from collections.abc import Mapping
from datetime import timedelta
from importlib.metadata import EntryPoint, EntryPoints
from typing import Any

import pytest

from notehub_client import simulate
from notehub_client.simulate import behaviors
from notehub_client.typing import Behavior, BehaviorFactory

P, D = "app:demo", "dev:temperature"


def scenario() -> simulate.Scenario:
    return simulate.Scenario().with_project(P).with_device(P, D)


@pytest.mark.asyncio
async def test_sensor_command_round_trip_and_stable_reads() -> None:
    with simulate.named("sensor").start(seed=7) as run:
        device = run.device(P, D)
        async with run.client() as client:
            assert (await client.devices.get(P, D))["temperature"] == 20
            run.advance(timedelta(minutes=1))
            assert device.readings["temperature"] == 20
            first = device.step()
            assert 20.08 <= first.readings["temperature"] <= 20.12
            assert not first.consumed  # Cloud command has not been delivered yet.
            assert device.sync().sent == 1
            second = device.step()
            assert 21.98 <= second.readings["temperature"] <= 22.02
            assert len(second.consumed) == 1
            assert device.receive("commands.qi") is None
            a = await client.devices.get(P, D)
            assert a == await client.devices.get(P, D)
            assert a["temperature"] == second.readings["temperature"]
            assert len((await client.events.list(P))["events"]) == 1
            device.sync()
            events = (await client.events.list(P))["events"]
            assert len(events) == 2
            assert events[-1]["body"]["celsius"] == second.readings["temperature"]
            assert run.snapshot()["devices"][(P, D)]["steps"] == 2


def test_seeded_runs_are_independent_and_devices_have_distinct_streams() -> None:
    definition = (
        scenario()
        .with_device(P, "dev:other")
        .with_behavior(P, D, "sensor", config={"noise": 1})
        .with_behavior(P, "dev:other", "sensor", config={"noise": 1})
    )
    with definition.start(seed=10) as a, definition.start(seed=10) as b:
        initial = b.snapshot()
        first = a.step()
        assert b.snapshot() == initial
        assert list(first) == [(P, D), (P, "dev:other")]
        assert first[(P, D)] != first[(P, "dev:other")]
        assert first == b.step()
        assert a.step() == b.step()
    with definition.start(seed=11) as c:
        assert first != c.step()


def test_factory_context_fluent_result_and_local_registry() -> None:
    contexts = []
    instances = []

    def factory(config: Mapping[str, Any], *, seed: int) -> Behavior:
        count = 0
        instances.append(seed)
        assert config == {"increment": 2}
        with pytest.raises(TypeError):
            config["increment"] = 99  # type: ignore

        def step(context: behaviors.StepContext) -> behaviors.StepResult:
            nonlocal count
            count += config["increment"]
            contexts.append(context)
            return (
                behaviors.StepResult()
                .with_readings(temperature=count)
                .with_note("data.qo", {"count": count})
            )

        return step

    typed: BehaviorFactory = factory
    registry = behaviors.BehaviorRegistry({"counter": typed}, plugins=False)
    definition = scenario().with_behavior(P, D, "counter", config={"increment": 2})
    with definition.start(registry=registry) as a, definition.start(registry=registry) as b:
        assert a.step() == b.step()
        a.device(P, D).step()
        assert len(instances) == 2
        assert contexts[-1].step == 2
        assert contexts[-1].readings == {"temperature": 2}
        with pytest.raises(TypeError):
            contexts[-1].readings["temperature"] = 99  # type: ignore
        assert a.device(P, D).readings == {"temperature": 4}
    assert definition == scenario().with_behavior(P, D, "counter", config={"increment": 2})


def test_direct_factory_and_unbound_device() -> None:
    definition = scenario().with_behavior(P, D, behaviors.sensor)
    with definition.start() as run:
        assert run.device(P, D).step().readings["temperature"] == 20.1
    with scenario().start() as run:
        assert run.step() == {}
        with pytest.raises(ValueError, match="no behavior"):
            run.device(P, D).step()
    with pytest.raises(RuntimeError, match="closed"):
        run.step()


@pytest.mark.parametrize("value", [True, "1", None])
def test_seed_requires_integer(value) -> None:
    with pytest.raises(TypeError, match="seed"):
        scenario().start(seed=value)


@pytest.mark.parametrize(
    "result",
    [
        None,
        behaviors.StepResult(readings={"temperature": 8}, consumed=("unknown",)),
    ],
)
def test_failed_step_leaves_simulation_state_unchanged(result) -> None:
    def factory(config, *, seed):
        return lambda context: result

    with scenario().with_behavior(P, D, factory).start() as run:
        before = run.snapshot()
        with pytest.raises((TypeError, ValueError)):
            run.device(P, D).step()
        assert run.snapshot() == before


def test_only_selected_commands_are_consumed() -> None:
    definition = (
        scenario()
        .with_behavior(P, D, "sensor")
        .with_inbound(P, D, "commands.qi", {"set_temperature": 12}, delivered=True)
        .with_inbound(P, D, "commands.qi", {"other": True}, delivered=True)
    )
    with definition.start() as run:
        device = run.device(P, D)
        result = device.step()
        assert result.readings["temperature"] == 12
        command = device.receive("commands.qi")
        assert command is not None and command["body"] == {"other": True}
        assert device.receive("commands.qi") is None


@pytest.mark.asyncio
async def test_static_readings_and_absent_measurements() -> None:
    definition = scenario().with_device(
        P, "dev:static", readings={"voltage": 3.5, "gps_location": {"lat": 45, "lon": -93}}
    )
    with definition.start() as run:
        async with run.client() as client:
            assert "temperature" not in await client.devices.get(P, D)
            assert "voltage" not in await client.devices.get(P, D)
            row = await client.devices.get(P, "dev:static")
            assert row["voltage"] == 3.5
            assert row["gps_location"] == {"lat": 45, "lon": -93}
            assert "temperature" not in row


@pytest.mark.parametrize(
    "values",
    [
        {"uid": "changed"},
        {"fleet_uids": []},
        {"last_activity": "changed"},
        {"temperature": True},
        {"voltage": "3.7"},
        {"temperature": float("inf")},
    ],
)
def test_readings_reject_invalid_values(values) -> None:
    with pytest.raises(ValueError):
        behaviors.StepResult(readings=values)
    with pytest.raises(ValueError):
        simulate.Device(P, D, readings=values)


def test_result_is_detached_and_supports_consumption() -> None:
    body = {"nested": [1]}
    result = behaviors.StepResult().with_note("data.qo", body).consuming("command:1")
    body["nested"].append(2)
    assert result.outbound[0].body["nested"] == (1,)
    assert result.consumed == ("command:1",)
    with pytest.raises(ValueError, match="unique"):
        result.consuming("command:1")
    with pytest.raises(ValueError, match=".qo"):
        result.with_note("data.qi", {})
    with pytest.raises(TypeError, match="OutboundNote"):
        behaviors.StepResult(outbound=({},))  # type: ignore


def test_bindings_require_existing_device_and_one_behavior() -> None:
    with pytest.raises(ValueError, match="unknown device"):
        scenario().with_behavior(P, "missing", "sensor")
    with pytest.raises(ValueError, match="one behavior"):
        scenario().with_behavior(P, D, "sensor").with_behavior(P, D, "sensor")
    with pytest.raises(ValueError, match="exactly one"):
        behaviors.BehaviorBinding(P, D)


def test_named_lookup_is_lazy_and_reports_ambiguous_plugins(monkeypatch) -> None:
    loaded = []
    entries = EntryPoints(
        [
            EntryPoint(
                name="external",
                value="some_plugin:factory",
                group="notehub_client.simulate.behaviors",
            ),
            EntryPoint(
                name="duplicate", value="a:factory", group="notehub_client.simulate.behaviors"
            ),
            EntryPoint(
                name="duplicate", value="b:factory", group="notehub_client.simulate.behaviors"
            ),
        ]
    )
    monkeypatch.setattr(behaviors.metadata, "entry_points", lambda **kw: entries.select(**kw))

    def load(entry):
        loaded.append(entry.name)
        return behaviors.sensor

    monkeypatch.setattr(EntryPoint, "load", load)
    registry = behaviors.BehaviorRegistry()
    definition = scenario().with_behavior(P, D, "external")
    assert registry.available() == ("duplicate", "external", "sensor")
    assert loaded == []
    with definition.start(registry=registry) as run:
        run.step()
    assert loaded == ["external"]
    with pytest.raises(ValueError, match="duplicate installed"):
        registry.resolve("duplicate")
    with pytest.raises(ValueError, match="unknown behavior"):
        registry.resolve("missing")
    local = behaviors.BehaviorRegistry({"external": behaviors.sensor}, plugins=False)
    assert local.resolve("external") is behaviors.sensor
    assert loaded == ["external"]
    with pytest.raises(ValueError, match="duplicate behavior"):
        local.register("external", behaviors.sensor)


@pytest.mark.parametrize("factory", [lambda config, seed: None, lambda config, seed: 3])
def test_factory_must_return_callable(factory) -> None:
    with pytest.raises(TypeError, match="return a callable"):
        scenario().with_behavior(P, D, factory).start()


def test_toml_local_name_is_resolved_at_start(datadir) -> None:
    definition = simulate.Scenario.from_toml(datadir / "counter.toml")
    with pytest.raises(ValueError, match="unknown behavior"):
        definition.start(registry=behaviors.BehaviorRegistry(plugins=False))
    registry = behaviors.BehaviorRegistry({"local": behaviors.sensor}, plugins=False)
    with definition.start(registry=registry) as run:
        assert run.device(P, D).step().readings["temperature"] == 10.5


def test_installed_distribution_entry_point(datadir, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(datadir / "plugins"))
    registry = behaviors.BehaviorRegistry()
    assert "example.sensor" in registry.available()
    definition = scenario().with_behavior(P, D, "example.sensor", config={"temperature": 8})
    with definition.start(registry=registry) as run:
        assert run.device(P, D).step().readings["temperature"] == 8.1


@pytest.mark.asyncio
async def test_behavior_receives_only_synchronized_environment_and_delivered_commands() -> None:
    contexts = []

    def factory(config, *, seed):
        def sample(context):
            contexts.append(context)
            return behaviors.StepResult()

        return sample

    definition = (
        simulate.Scenario()
        .with_project(P, environment={"MODE": "cloud"})
        .with_device(P, D, defaults={"MODE": "default"})
        .with_behavior(P, D, factory)
    )
    with definition.start() as run:
        device = run.device(P, D)
        async with run.client() as client:
            await client.notes.add_qi(device.note("commands.qi"), {"test": True})
            device.step()
            assert contexts[-1].environment == {"MODE": "default"}
            assert contexts[-1].commands == ()
            device.sync()
            device.step()
            assert contexts[-1].environment == {"MODE": "cloud"}
            assert len(contexts[-1].commands) == 1
            command = contexts[-1].commands[0]
            with pytest.raises(TypeError):
                command["body"]["test"] = False
            assert device.receive("commands.qi") is not None


def test_failed_device_does_not_undo_earlier_devices() -> None:
    def factory(config, *, seed):
        def sample(context):
            raise RuntimeError("model failed")

        return sample

    definition = (
        scenario()
        .with_device(P, "dev:other")
        .with_behavior(P, D, "sensor")
        .with_behavior(P, "dev:other", factory)
    )
    with definition.start() as run:
        with pytest.raises(RuntimeError, match="model failed"):
            run.step()
        assert run.snapshot()["devices"][(P, D)]["steps"] == 1
        assert run.snapshot()["devices"][(P, "dev:other")]["steps"] == 0


@pytest.mark.parametrize(
    "config",
    [
        {"noise": -1},
        {"temperature": True},
        {"voltage": "3.7"},
        {"unknown": 1},
        {"notefile": "data.qi"},
    ],
)
def test_sensor_configuration_errors(config) -> None:
    with pytest.raises(ValueError):
        scenario().with_behavior(P, D, "sensor", config=config).start()


def test_adding_device_does_not_change_existing_random_stream() -> None:
    definition = scenario().with_behavior(P, D, "sensor", config={"noise": 1})
    extended = definition.with_device(P, "dev:other").with_behavior(
        P, "dev:other", "sensor", config={"noise": 1}
    )
    with definition.start(seed=4) as a, extended.start(seed=4) as b:
        for _ in range(3):
            assert a.device(P, D).step() == b.device(P, D).step()


def test_bad_plugin_factory_and_disabled_discovery(monkeypatch) -> None:
    entries = EntryPoints(
        [EntryPoint(name="broken", value="bad:factory", group="notehub_client.simulate.behaviors")]
    )
    calls = []

    def discover(**kw):
        calls.append(kw)
        return entries.select(**kw)

    monkeypatch.setattr(behaviors.metadata, "entry_points", discover)
    monkeypatch.setattr(EntryPoint, "load", lambda entry: 3)
    with pytest.raises(TypeError, match="load a factory"):
        behaviors.BehaviorRegistry().resolve("broken")
    calls.clear()
    registry = behaviors.BehaviorRegistry(plugins=False)
    assert registry.available() == ("sensor",)
    with pytest.raises(ValueError, match="unknown behavior"):
        registry.resolve("broken")
    assert calls == []
