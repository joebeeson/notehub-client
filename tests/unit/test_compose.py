from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import httpx
import pytest
import respx

from notehub_client import NotehubClient, compose
from notehub_client.compose import Composer, DeviceTarget, NoteTarget

composer = Composer()


@dataclass
class NestedReading:
    value: float

    def to_json_value(self) -> object:
        return {"value": self.value}


class ThirdPartyReading:
    def __init__(self, value: str) -> None:
        self.value = value


@composer.json_value.register(ThirdPartyReading)
def _third_party_reading(value: ThirdPartyReading) -> object:
    return {"external": value.value}


@dataclass
class AppNote:
    reading: NestedReading

    def to_note_body(self) -> Mapping[str, object]:
        return {"reading": self.reading, "tags": ("indoor", "test")}


@dataclass
class EnvValue:
    value: int

    def to_environment_value(self) -> str:
        return str(self.value)


class ExternalDevice:
    project = "app:registered"
    device = "dev:registered"


@composer.notehub_target.register(ExternalDevice)
def _external_device(value: ExternalDevice) -> DeviceTarget:
    return DeviceTarget(value.project, value.device)


class ExternalKey:
    value = "upload_interval"


@composer.notehub_identifier.register(ExternalKey)
def _external_key(value: ExternalKey) -> str:
    return value.value


class StructuralDevice:
    def to_notehub_target(self) -> DeviceTarget:
        return DeviceTarget("app:structural", "dev:structural")


class StructuralKey:
    def to_notehub_identifier(self) -> str:
        return "structural_key"


class AppEnvironment:
    def to_environment_values(self) -> Mapping[str, object]:
        return {"limit": EnvValue(5)}


def test_resolve_json_walks_nodes_and_converts_structural_and_registered_leaves() -> None:
    assert compose.resolve_json(
        {
            "items": [NestedReading(1.5), ThirdPartyReading("from-adapter")],
            "tuple": (True, None),
        },
        composer=composer,
    ) == {
        "items": [{"value": 1.5}, {"external": "from-adapter"}],
        "tuple": [True, None],
    }


def test_resolve_note_body_accepts_a_structural_top_level_object() -> None:
    assert compose.resolve_note_body(AppNote(NestedReading(21.5))) == {
        "reading": {"value": 21.5},
        "tags": ["indoor", "test"],
    }


def test_registered_converter_overrides_structural_method() -> None:
    class Both:
        def to_json_value(self) -> object:
            return "protocol"

    @composer.json_value.register(Both)
    def _registered(_value: Both) -> object:
        return "registered"

    assert compose.resolve_json(Both(), composer=composer) == "registered"


@pytest.mark.parametrize(
    ("value", "error", "message"),
    [
        pytest.param(float("inf"), ValueError, "non-finite number at", id="infinity"),
        pytest.param({1: "bad"}, TypeError, "non-string object key", id="non-string-key"),
        pytest.param(
            {"bad": object()}, TypeError, "unsupported JSON value at", id="unsupported-leaf"
        ),
    ],
)
def test_resolve_json_rejects_invalid_values(
    value: object, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        compose.resolve_json(value)


def test_resolve_json_rejects_cycles_without_including_values() -> None:
    cycle: dict[str, object] = {}
    cycle["self"] = cycle
    with pytest.raises(ValueError, match="cyclic value at") as exc:
        compose.resolve_json(cycle)
    assert "self" in str(exc.value)
    assert "<object" not in str(exc.value)


def test_environment_resolution_requires_explicit_string_conversion() -> None:
    assert compose.resolve_environment({"limit": EnvValue(3), "mode": "quiet"}) == {
        "limit": "3",
        "mode": "quiet",
    }
    with pytest.raises(TypeError, match="implement to_environment_value"):
        compose.resolve_environment({"limit": 3})
    assert compose.resolve_environment(AppEnvironment()) == {"limit": "5"}


def test_target_and_identifier_converters_validate_their_results() -> None:
    target = compose.resolve_target(ExternalDevice(), composer=composer)
    assert target == DeviceTarget("app:registered", "dev:registered")
    assert compose.resolve_target(StructuralDevice()) == DeviceTarget(
        "app:structural", "dev:structural"
    )
    assert compose.resolve_identifier(ExternalKey(), composer=composer) == "upload_interval"
    assert compose.resolve_identifier(StructuralKey()) == "structural_key"
    with pytest.raises(TypeError, match="DeviceTarget or NoteTarget"):
        compose.resolve_target(object())


@pytest.mark.asyncio
@respx.mock
async def test_facades_accept_composed_targets_payloads_and_identifiers() -> None:
    base = "https://api.notefile.net/v1/projects/app:test/devices/dev:one"
    queue = respx.post(f"{base}/notes/readings.qi").mock(return_value=httpx.Response(204))
    add = respx.post(f"{base}/notes/readings.db/latest").mock(return_value=httpx.Response(204))
    update = respx.put(f"{base}/notes/readings.db/latest").mock(return_value=httpx.Response(204))
    delete = respx.delete(f"{base}/notes/readings.db/latest").mock(return_value=httpx.Response(204))
    environment = respx.put(f"{base}/environment_variables").mock(return_value=httpx.Response(204))
    delete_environment = respx.delete(f"{base}/environment_variables/upload_interval").mock(
        return_value=httpx.Response(204)
    )
    get_environment = respx.get(
        "https://api.notefile.net/v1/projects/app:registered/devices/dev:registered/environment_variables"
    ).mock(return_value=httpx.Response(200, json={"environment_variables": {"mode": "quiet"}}))

    target = NoteTarget("app:test", "dev:one", "readings.db", "latest")
    queue_target = NoteTarget("app:test", "dev:one", "readings.qi")
    device = DeviceTarget("app:test", "dev:one")
    async with NotehubClient("pat", composer=composer) as client:
        assert await client.notes.add_qi(queue_target, {"reading": NestedReading(20.0)}) is None
        assert await client.notes.add_db(target, AppNote(NestedReading(21.5))) is None
        assert await client.notes.update_db(target=target, body={"ok": True}) is None
        assert await client.notes.delete(target) is None
        assert (
            await client.devices.set_environment(device, {"upload_interval": EnvValue(3)}) is None
        )
        assert await client.devices.delete_environment_variable(device, ExternalKey()) is None
        assert await client.devices.get_environment(ExternalDevice()) == {
            "environment_variables": {"mode": "quiet"}
        }

    assert add.calls[0].request.content == (
        b'{"body":{"reading":{"value":21.5},"tags":["indoor","test"]}}'
    )
    assert queue.calls[0].request.content == b'{"body":{"reading":{"value":20.0}}}'
    assert update.calls[0].request.content == b'{"body":{"ok":true}}'
    assert environment.calls[0].request.content == (
        b'{"environment_variables":{"upload_interval":"3"}}'
    )
    assert all(
        route.called
        for route in (queue, add, update, delete, environment, delete_environment, get_environment)
    )


@pytest.mark.asyncio
@respx.mock
async def test_invalid_composition_fails_before_request() -> None:
    async with NotehubClient("pat", composer=composer) as client:
        with pytest.raises(TypeError, match="note body"):
            await client.notes.add_qi("app:test", "dev:one", "readings.qi", object())
        with pytest.raises(ValueError, match="note_id"):
            await client.notes.delete(NoteTarget("app:test", "dev:one", "readings.db"))
        with pytest.raises(TypeError, match="strings or implement"):
            await client.devices.set_environment(DeviceTarget("app:test", "dev:one"), {"limit": 3})


def test_all_adapter_roles_are_independent_snapshots() -> None:
    class External:
        pass

    configured = Composer()
    outputs = {
        "note_body": {"reading": 1},
        "json_value": 1,
        "environment_values": {"interval": "1"},
        "environment_value": "1",
        "notehub_identifier": "external",
        "notehub_target": DeviceTarget("p", "d"),
    }
    for name, result in outputs.items():
        getattr(configured, name).register(External, lambda _, result=result: result)
    snapshot = configured.copy(frozen=True)
    for name, result in outputs.items():
        getattr(configured, name).register(External, lambda _: "changed")
        assert getattr(snapshot, name)(External()) == result
        with pytest.raises(RuntimeError):
            getattr(snapshot, name).register(External, lambda _: "changed")
    assert snapshot.resolve_note_body(External()) == {"reading": 1}
    assert snapshot.resolve_environment(External()) == {"interval": "1"}
    assert snapshot.resolve_identifier(External()) == "external"
    assert snapshot.resolve_target(External()) == DeviceTarget("p", "d")
    assert not hasattr(compose.json_value, "register")
