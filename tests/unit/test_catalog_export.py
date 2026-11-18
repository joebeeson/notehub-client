"""Portable export through the existing loader and sample validator."""

from collections.abc import MutableMapping
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from notehub_client.catalog import (
    Catalog,
    CatalogArtifacts,
    CatalogError,
    Contract,
    EventSelector,
    export_artifacts,
    load,
    loads,
)
from notehub_client.catalog.loading import ASYNCAPI_FORMAT, JSON_FORMAT
from notehub_client.catalog.validation import validate_sample
from notehub_client.typing.json import JSONScalar


def test_example_catalog_can_be_written_as_a_self_contained_bundle(tmp_path: Path) -> None:
    source = load(Path(__file__).resolve().parents[2] / "examples/payload_catalog/catalog.toml")
    artifacts = export_artifacts(source)
    for name, text in artifacts.documents.items():
        (tmp_path / name).write_text(text, encoding="utf-8", newline="\n")
    manifest = tmp_path / "catalog.toml"
    manifest.write_text(artifacts.manifest, encoding="utf-8", newline="\n")
    restored = load(manifest)
    assert list(restored) == list(source)
    for key in source:
        assert restored[key].selector == source[key].selector
        assert restored[key].binding == source[key].binding


@pytest.mark.parametrize("value", [None, False, True, 0, 1, 1.25, "", 'quote"\n\x00\x7f🌱'])
@pytest.mark.parametrize("schema_format", [JSON_FORMAT, ASYNCAPI_FORMAT])
def test_metadata_and_scalar_round_trip(value: JSONScalar, schema_format: str) -> None:
    selector = EventSelector(product="p🌱", file_glob="*.qo", discriminator="/body/v", value=value)
    contract = replace(
        Contract('sensor"\n🌱', "opaque-version", selector, binding="binding\t🌱").with_schema(
            True
        ),
        schema_format=schema_format,
    )
    fallback = Contract("fallback", "0").with_schema(False)
    catalog = Catalog([contract, fallback])
    artifacts = export_artifacts(catalog)
    assert artifacts == export_artifacts(catalog)
    restored = loads(artifacts.manifest, read_document=artifacts.documents.__getitem__)
    assert list(restored) == list(catalog)
    for key in catalog:
        assert replace(restored[key], message_ref=catalog[key].message_ref) == catalog[key]
    for event in [{"product": "p🌱", "file": "sensor.qo", "body": {"v": value}}, {}]:
        assert restored.resolve(event).key == catalog.resolve(event).key
    ambiguous = catalog.add(replace(contract, version="other"))
    bundle = export_artifacts(ambiguous)
    copy = loads(bundle.manifest, read_document=bundle.documents.__getitem__)
    with pytest.raises(CatalogError, match="ambiguous"):
        copy.resolve({"product": "p🌱", "file": "sensor.qo", "body": {"v": value}})


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {"child": {"$ref": "#"}}, "additionalProperties": False},
        {
            "$ref": "#/definitions/a~1b%20🌱",
            "definitions": {
                "a/b 🌱": {
                    "type": "object",
                    "properties": {"next": {"$ref": "#/definitions/b"}},
                    "additionalProperties": False,
                },
                "b": {
                    "type": "object",
                    "properties": {"next": {"$ref": "#/definitions/a~1b%20🌱"}},
                    "additionalProperties": False,
                },
            },
        },
    ],
)
def test_recursive_schema_validation_survives_export(schema: dict) -> None:
    original = Contract("recursive", "1").with_schema(schema)
    artifacts = export_artifacts(Catalog([original]))
    restored = loads(artifacts.manifest, read_document=artifacts.documents.__getitem__)[
        original.key
    ]
    for sample in [{}, {"child": {}}, {"next": {"next": {}}}, {"child": 3}, 42]:
        assert bool(validate_sample(original, sample)) == bool(validate_sample(restored, sample))
    assert original.schema == schema
    # Export an already bundled loader result as well as the programmatic schema.
    again = export_artifacts(Catalog([restored]))
    reloaded = loads(again.manifest, read_document=again.documents.__getitem__)[original.key]
    assert not validate_sample(reloaded, {})
    assert validate_sample(reloaded, 42)


def test_literal_references_empty_pointer_and_immutable_artifacts() -> None:
    literal = {"$ref": "https://example.invalid/literal", "$id": "literal"}
    contract = Contract("literal", "1", EventSelector(discriminator="", value=None)).with_schema(
        {"const": literal}
    )
    artifacts = export_artifacts(Catalog([contract]))
    restored = loads(artifacts.manifest, read_document=artifacts.documents.__getitem__)[
        contract.key
    ]
    assert restored.selector == contract.selector
    assert restored.schema == contract.schema
    assert not validate_sample(restored, literal)
    with pytest.raises(TypeError):
        cast("MutableMapping[str, str]", artifacts.documents)["new.json"] = "{}"
    documents = {"a.json": "{}"}
    owned = CatalogArtifacts("", documents)
    documents.clear()
    assert owned.documents == {"a.json": "{}"}
    empty = export_artifacts(Catalog())
    assert not loads(empty.manifest, read_document=empty.documents.__getitem__)
    assert not empty.documents


@pytest.mark.parametrize(
    "contract",
    [
        Contract("bad", "1"),
        replace(Contract("bad", "1").with_schema(True), schema_format="unsupported"),
        Contract("bad", "1").with_schema({"$id": "https://example.invalid/schema"}),
        Contract("bad", "1").with_schema({"$ref": "https://example.invalid/schema"}),
        Contract("bad", "1").with_schema({"$ref": "#anchor"}),
        Contract("bad", "1").with_schema({"$ref": "#/missing"}),
        Contract("bad", "1").with_schema({"$ref": "#/type", "type": "string"}),
    ],
)
def test_unsupported_contracts_fail_without_partial_artifacts(contract: Contract) -> None:
    with pytest.raises(CatalogError) as caught:
        export_artifacts(Catalog([Contract("good", "1").with_schema(True), contract]))
    assert caught.value.stage == "export"
    assert caught.value.keys == (contract.key,)
    assert "example.invalid" not in str(caught.value)
