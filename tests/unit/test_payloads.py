from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import httpx
import pytest
import respx
from cattrs import Converter

from notehub_client import NotehubClient
from notehub_client.catalog import Catalog, Contract, EventSelector
from notehub_client.compose import Composer
from notehub_client.payloads import PayloadDecodeError, PayloadDecoder
from notehub_client.typing import Event


@dataclass
class ReadingV1:
    fahrenheit: float


@dataclass
class Reading:
    celsius: float


def upgrade(value: ReadingV1) -> Reading:
    return Reading((value.fahrenheit - 32) * 5 / 9)


def decoder() -> PayloadDecoder:
    catalog = Catalog(
        (
            Contract("reading", "1", EventSelector(discriminator="/body/v", value=1), binding="v1"),
            Contract("reading", "2", EventSelector(discriminator="/body/v", value=2), binding="v2"),
        )
    )
    return PayloadDecoder(
        catalog=catalog,
        bindings={"v1": ReadingV1, "v2": Reading},
        upgrades={(("reading", "1"), Reading): upgrade},
    )


def test_source_decoding_and_explicit_upgrade_preserve_raw() -> None:
    event: Event = {"body": {"v": 1, "fahrenheit": 68}}
    result = decoder().decode(event, as_type=Reading)
    assert result.body == Reading(20)
    assert result.raw is event
    assert event["body"] == {"v": 1, "fahrenheit": 68}
    assert result.contract.key == ("reading", "1")
    assert decoder().decode(event, as_type=ReadingV1).body == ReadingV1(68)
    assert decoder().decode(
        {"body": {"fahrenheit": 68}}, as_type=ReadingV1, contract=("reading", "1")
    ).body == ReadingV1(68)


def test_no_validation_on_decode_and_unbound_targets() -> None:
    # A deliberately incompatible portable schema has no effect on decoding.
    contract = Contract("reading", "1").with_schema(False)
    result = PayloadDecoder(catalog=Catalog((contract,))).decode(
        {"body": {"celsius": 12}}, as_type=Reading
    )
    assert result.body == Reading(12)


def test_nested_errors_and_missing_contract_body_upgrade() -> None:
    event: Event = {"body": {"v": 1, "fahrenheit": "secret"}}
    with pytest.raises(PayloadDecodeError) as exc:
        decoder().decode(event, as_type=Reading)
    assert exc.value.stage == "structure"
    assert exc.value.paths == ("$.fahrenheit",)
    assert exc.value.__cause__ is not None
    assert "secret" not in str(exc.value)
    for data, key, stage in [
        ({}, None, "selection"),
        ({}, ("reading", "1"), "body"),
        ({"body": {"v": 2, "celsius": 1}}, None, "upgrade_lookup"),
    ]:
        with pytest.raises(PayloadDecodeError) as exc:
            decoder().decode(cast("Event", data), as_type=ReadingV1, contract=key)
        assert exc.value.stage == stage


def test_converter_and_binding_snapshot_protect_input() -> None:
    converter = Converter()

    def mutating_hook(body: dict, _: object) -> Reading:
        return Reading(body.pop("celsius"))

    converter.register_structure_hook(Reading, mutating_hook)
    bindings = {"v": Reading}
    payloads = PayloadDecoder(
        catalog=Catalog((Contract("r", "1", binding="v"),)), bindings=bindings, converter=converter
    )
    converter.register_structure_hook(Reading, lambda *_: Reading(99))
    bindings.clear()
    event: Event = {"body": {"celsius": 3}}
    assert payloads.decode(event, as_type=Reading).body == Reading(3)
    assert event["body"] == {"celsius": 3}


@pytest.mark.asyncio
@respx.mock
async def test_typed_iteration_follows_existing_pagination() -> None:
    route = respx.get("https://api.notefile.net/v1/projects/p/events")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "events": [{"body": {"v": 1, "fahrenheit": 68}}],
                "has_more": True,
                "next_cursor": "next",
            },
        ),
        httpx.Response(
            200, json={"events": [{"body": {"v": 2, "celsius": 25}}], "has_more": False}
        ),
    ]
    async with NotehubClient("pat", payloads=decoder()) as client:
        results = [item async for item in client.events.iter_decoded("p", as_type=Reading)]
    assert [item.body for item in results] == [Reading(20), Reading(25)]
    assert route.calls[1].request.url.params["cursor"] == "next"


@pytest.mark.asyncio
@respx.mock
async def test_composer_client_snapshots_and_write_isolation() -> None:
    first = Composer()
    first.json_value.register(Reading, lambda value: value.celsius)
    second = Composer()
    second.json_value.register(Reading, lambda value: {"temperature": value.celsius})
    route = respx.post("https://api.notefile.net/v1/projects/p/devices/d/notes/r.qi").mock(
        return_value=httpx.Response(204)
    )
    async with (
        NotehubClient("pat", composer=first) as a,
        NotehubClient("pat", composer=second) as b,
    ):
        first.json_value.register(Reading, lambda _: "changed")
        await a.notes.add_qi("p", "d", "r.qi", {"r": Reading(3)})
        await b.notes.add_qi("p", "d", "r.qi", {"r": Reading(3)})
        assert json_body(route.calls[0].request) == {"body": {"r": 3}}
        assert json_body(route.calls[1].request) == {"body": {"r": {"temperature": 3}}}
        with pytest.raises(RuntimeError):
            a.composer.json_value.register(Reading, lambda _: 0)
    with pytest.raises(TypeError):
        Composer().resolve_json(Reading(3))


def json_body(request: httpx.Request) -> object:
    import json

    return json.loads(request.content)


def test_failed_upgrade_is_not_retried_and_keeps_cause() -> None:
    count = 0

    def broken(_: ReadingV1) -> Reading:
        nonlocal count
        count += 1
        raise ValueError("sensitive input")

    base = decoder()
    failing = PayloadDecoder(
        catalog=base.catalog, bindings=base.bindings, upgrades={(("reading", "1"), Reading): broken}
    )
    with pytest.raises(PayloadDecodeError) as exc:
        failing.decode({"body": {"v": 1, "fahrenheit": 68}}, as_type=Reading)
    assert exc.value.stage == "upgrade"
    assert count == 1
    assert isinstance(exc.value.__cause__, ValueError)
    assert "sensitive" not in str(exc.value)


def test_generic_requested_type_and_nested_validation_paths() -> None:
    payloads = PayloadDecoder(catalog=Catalog((Contract("r", "1"),)))
    result = payloads.decode({"body": {"celsius": 2}}, as_type=dict[str, float])
    assert result.body == {"celsius": 2}

    @dataclass
    class Batch:
        readings: list[Reading]

    with pytest.raises(PayloadDecodeError) as exc:
        payloads.decode(
            cast("Event", {"body": {"readings": [{"celsius": "secret"}]}}), as_type=Batch
        )
    assert exc.value.paths == ("$.readings[0].celsius",)


@pytest.mark.asyncio
@respx.mock
async def test_iteration_propagates_decode_failure_and_raw_reads_remain_available() -> None:
    respx.get("https://api.notefile.net/v1/projects/p/events").respond(
        200,
        json={
            "events": [{"body": {"v": 99, "celsius": 1}}],
            "has_more": False,
        },
    )
    async with NotehubClient("pat", payloads=decoder()) as client:
        assert (await client.events.list("p"))["events"][0]["body"]["v"] == 99
        with pytest.raises(PayloadDecodeError):
            _ = [item async for item in client.events.iter_decoded("p", as_type=Reading)]
