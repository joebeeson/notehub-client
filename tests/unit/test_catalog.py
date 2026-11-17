from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from notehub_client.catalog import Catalog, CatalogError, Contract, EventSelector, load, loads
from notehub_client.catalog.sources import load_sources
from notehub_client.catalog.validation import validate_sample


def test_ordered_layering_and_version_ambiguity() -> None:
    first = Contract("reading", "1", EventSelector(product="p", file_glob="*.qo"))
    second = Contract("fallback", "1")
    catalog = Catalog((first, second))
    replacement = Contract("reading", "1", first.selector, binding="reading")
    layered = catalog.add(replacement)
    assert list(layered) == [("reading", "1"), ("fallback", "1")]
    assert layered.resolve({"product": "p", "file": "readings.qo"}) == replacement
    assert catalog[first.key] == first
    ambiguous = layered.add(Contract("reading", "2", first.selector))
    with pytest.raises(CatalogError) as exc:
        ambiguous.resolve({"product": "p", "file": "readings.qo"})
    assert exc.value.keys == (("reading", "1"), ("reading", "2"))
    assert catalog.resolve({}) == second
    with pytest.raises(CatalogError):
        Catalog((first,)).resolve({"file": "readings.qo"})


def test_catalog_and_schemas_accept_mapping_interfaces() -> None:
    from types import MappingProxyType

    entry = Contract("r", "1").with_schema(
        MappingProxyType(
            {
                "type": "object",
                "properties": MappingProxyType({"x": {"type": "number"}}),
            }
        )
    )
    catalog = Catalog(MappingProxyType({entry.key: entry}))
    assert Catalog(catalog) == catalog
    assert validate_sample(entry, {"x": 1}) == ()
    with pytest.raises(ValueError):
        Catalog({("r", "other"): entry})


def test_discriminators_pointer_escaping_and_scalar_equality() -> None:
    selector = EventSelector(discriminator="/body/a~1b/~0version/0", value=1)
    assert selector.matches({"body": {"a/b": {"~version": [1]}}})
    assert not selector.matches({"body": {"a/b": {"~version": [True]}}})
    assert not selector.matches({"body": {}})
    assert not selector.matches({"body": {"a/b": {"~version": []}}})
    assert EventSelector(discriminator="/body/v", value=None).matches({"body": {"v": None}})
    assert not EventSelector(discriminator="/body/v", value=None).matches({"body": {}})
    with pytest.raises(ValueError):
        EventSelector(discriminator="/bad~2")
    with pytest.raises(ValueError):
        EventSelector(file="x", file_glob="*")
    assert selector.where(value=2).value == 2


TOML = """catalog_version = 1
[[contracts]]
id = "reading"
version = "1"
binding = "reading.v1"
message_ref = "messages.json#/channels/readings/messages/reading"
[contracts.selector]
product = "p"
file = "readings.qo"
discriminator = "/body/v"
value = 1
"""

DOCUMENT = {
    "asyncapi": "3.1.0",
    "info": {"title": "Readings", "version": "1.0.0"},
    "channels": {
        "readings": {
            "address": "readings.qo",
            "messages": {
                "reading": {"$ref": "#/components/messages/Reading"},
            },
        }
    },
    "components": {
        "messages": {"Reading": {"payload": {"$ref": "#/components/schemas/Reading"}}},
        "schemas": {
            "Reading": {
                "type": "object",
                "properties": {"v": {"const": 1}, "celsius": {"type": "number"}},
                "required": ["v", "celsius"],
            }
        },
    },
}


def test_artifact_loading_matches_python_and_stream_construction(tmp_path: Path) -> None:
    path = tmp_path / "catalog.toml"
    path.write_text(TOML)
    (tmp_path / "messages.json").write_text(json.dumps(DOCUMENT))
    catalog = load(path)
    expected = Contract(
        "reading",
        "1",
        EventSelector(product="p", file="readings.qo", discriminator="/body/v", value=1),
        message_ref="messages.json#/channels/readings/messages/reading",
        binding="reading.v1",
        schema_format="application/vnd.aai.asyncapi+json;version=3.1.0",
    ).with_schema(DOCUMENT["components"]["schemas"]["Reading"])
    assert catalog == Catalog((expected,))
    assert load(io.StringIO(TOML), read_document=lambda _: json.dumps(DOCUMENT)) == catalog
    schema = catalog[expected.key].schema
    assert isinstance(schema, dict)
    schema["required"].clear()
    fresh_schema = catalog[expected.key].schema
    assert isinstance(fresh_schema, dict)
    assert fresh_schema["required"] == ["v", "celsius"]


def test_validation_is_explicit_and_reports_locations_without_values() -> None:
    contract = loads(TOML, read_document=lambda _: json.dumps(DOCUMENT))[("reading", "1")]
    assert validate_sample(contract, {"v": 1, "celsius": 20}) == ()
    issues = validate_sample(contract, {"v": 1, "celsius": "secret"})
    assert issues[0].instance_path == ("celsius",)
    assert "secret" not in repr(issues)
    with pytest.raises(CatalogError):
        validate_sample(Contract("missing", "1"), {})
    with pytest.raises(CatalogError):
        validate_sample(contract.with_schema({"$schema": "unknown"}), {})


def test_yaml_and_recursive_document_schema_references() -> None:
    import yaml

    doc = json.loads(json.dumps(DOCUMENT))
    doc["components"]["schemas"]["Reading"]["properties"]["child"] = {
        "$ref": "#/components/schemas/Reading"
    }
    catalog = loads(
        TOML.replace("messages.json", "messages.yaml"), read_document=lambda _: yaml.safe_dump(doc)
    )
    assert (
        validate_sample(
            catalog[("reading", "1")], {"v": 1, "celsius": 10, "child": {"v": 1, "celsius": 12}}
        )
        == ()
    )


@pytest.mark.parametrize("change", ["version", "format", "external"])
def test_unsupported_artifacts_fail_explicitly(change: str) -> None:
    doc = json.loads(json.dumps(DOCUMENT))
    if change == "version":
        doc["asyncapi"] = "2.6.0"
    elif change == "format":
        doc["components"]["messages"]["Reading"]["payload"] = {"schemaFormat": "avro", "schema": {}}
    else:
        doc["components"]["schemas"]["Reading"]["properties"]["extra"] = {
            "$ref": "other.json#/schema"
        }
    with pytest.raises(CatalogError) as exc:
        loads(TOML, read_document=lambda _: json.dumps(doc))
    assert exc.value.stage == "load"


def test_fsspec_sources_sorted_and_protocols_mixed(tmp_path: Path) -> None:
    import fsspec

    fs = fsspec.filesystem("memory")
    fs.pipe("/catalog-test/messages.json", json.dumps(DOCUMENT).encode())
    fs.pipe("/catalog-test/b.toml", TOML.replace('version = "1"', 'version = "2"').encode())
    fs.pipe("/catalog-test/a.toml", TOML.encode())
    path = tmp_path / "local.toml"
    path.write_text(TOML.replace('id = "reading"', 'id = "other"'))
    (tmp_path / "messages.json").write_text(json.dumps(DOCUMENT))
    catalog = load_sources("memory:///catalog-test", str(path))
    assert list(catalog) == [("reading", "1"), ("reading", "2"), ("other", "1")]
    assert load_sources("memory:///catalog-test/*.toml") == Catalog(tuple(catalog.values())[:2])
    with pytest.raises(CatalogError):
        load_sources("memory:///catalog-test/missing-*.toml")


def test_schema_literal_data_is_never_interpreted_as_references() -> None:
    doc = json.loads(json.dumps(DOCUMENT))
    doc["components"]["schemas"]["Reading"]["examples"] = [
        {"$ref": "literal-not-a-reference", "discriminator": "literal"}
    ]
    contract = loads(TOML, read_document=lambda _: json.dumps(doc))[("reading", "1")]
    assert validate_sample(contract, {"v": 1, "celsius": 20}) == ()


@pytest.mark.parametrize(
    "module, action, extra",
    [
        ("yaml", "yaml", "yaml"),
        ("jsonschema", "validate", "validate"),
        ("fsspec.core", "sources", "fsspec"),
    ],
)
def test_optional_dependencies_fail_with_install_guidance(
    monkeypatch: pytest.MonkeyPatch,
    module: str,
    action: str,
    extra: str,
) -> None:
    import sys

    from notehub_client.errors import NotehubDependencyError

    monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(NotehubDependencyError) as exc:
        if action == "yaml":
            loads(TOML.replace("messages.json", "messages.yaml"), read_document=lambda _: "{}")
        elif action == "validate":
            validate_sample(Contract("x", "1").with_schema(True), {})
        else:
            load_sources("memory:///anything")
    assert exc.value.extra == extra
