# Payload catalogs and client conversion

Use `notehub_client.catalog` to describe payload contracts and
`notehub_client.payloads.PayloadDecoder` to connect them to Python types.
The [complete local example](../examples/payload_catalog/readings.py) includes an
AsyncAPI document, a TOML companion, two wire versions, an upgrade, and explicit
sample validation. Run it with:

```console
uv run --extra validate examples/payload_catalog/readings.py
```

## Build and layer catalogs

```python
from notehub_client.catalog import Catalog, Contract, EventSelector, load

base = Catalog(
    [Contract("reading", "1", EventSelector(product="product:example", file="readings.qo"))]
)
catalog = base.overlay(load("catalog.toml"))
```

Catalogs are immutable ordered mappings keyed by `(contract_id, schema_version)`.
`add()` and `overlay()` return new catalogs; replacing a key retains its position.
The first matching family wins. All matching versions within that family are
considered: multiple versions raise an ambiguity error. Versions are opaque
strings and never imply a latest version. Selectors use the event's `product`
and `file` fields; `file_glob` provides case-sensitive glob matching instead of
an exact `file`. `selector.where(...)` returns a modified selector.

An event-relative JSON Pointer and scalar discriminator can distinguish formats
sharing product/file metadata. A missing path does not match; JSON `true` does
not match the number `1`. For unversioned historical data, pass an explicit
contract key to `decode()` to bypass automatic selection.

Pointer syntax is checked before reading event fields: escape `/` as `~1` and
`~` as `~0`. An empty pointer addresses the whole event; `/` addresses an empty
object key. Malformed syntax is a configuration error rather than a non-match.

The TOML format uses `catalog_version = 1` and `[[contracts]]` entries with `id`,
`version`, `message_ref`, optional `binding`, and an optional `[contracts.selector]`.
Each `message_ref` names a relative AsyncAPI document plus a JSON Pointer fragment.
Bindings are names resolved through Python configuration; artifacts never import
Python classes or execute callables.

Version 1 rejects unknown fields in the manifest and contract tables, along with
duplicate `(id, version)` entries in one file. Manifest metadata is validated
before companion documents are read. Use separate catalogs and `overlay()` when
you intend to replace an existing version.

The initial profile supports AsyncAPI 3.1.0 JSON documents and, with the `yaml`
extra, safe YAML documents. Messages may be addressed through channels or reusable
components. Payloads may use AsyncAPI 3.1 schemas or explicit JSON Schema Draft 07.
Document-relative references are bundled at load time, including recursive payload
schemas. External AsyncAPI references, other specification versions, and other
schema formats raise `CatalogError`. This focused loader does not certify full
AsyncAPI document validity or execute operations, traits, or protocol bindings.

Streams use `load(stream, read_document=reader)`; strings use
`loads(toml_text, read_document=reader)`. The reader receives document names as
written in TOML. Local file references resolve relative to the TOML file.

```python
from notehub_client.catalog.sources import load_sources

catalog = load_sources("./contracts", "s3://example/contracts/*.toml")
```

Install the `fsspec` extra and the filesystem's own backend when needed. Sources
can use different protocols. Directories select immediate TOML children; glob
matches and directory children are sorted within each source. Later sources
overlay earlier ones. No artifact I/O takes place during decoding.

## Export portable artifacts

`export_artifacts(catalog)` returns an immutable `CatalogArtifacts` bundle with
TOML text in `manifest` and JSON companion texts in `documents`. It performs no
file or network I/O. Round-trip entirely in memory with:

```python
from notehub_client.catalog import export_artifacts, loads

artifacts = export_artifacts(catalog)
restored = loads(artifacts.manifest, read_document=artifacts.documents.__getitem__)
```

To write an isolated bundle explicitly:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from notehub_client.catalog import load

with TemporaryDirectory() as directory:
    target = Path(directory)
    for name, text in artifacts.documents.items():
        (target / name).write_text(text, encoding="utf-8", newline="\n")
    manifest = target / "catalog.toml"
    manifest.write_text(artifacts.manifest, encoding="utf-8", newline="\n")
    restored = load(manifest)
```

Export preserves contract order, selectors, binding names, schema formats, and
validation behavior. It generates new message references; the catalog does not
retain original channels, operations, comments, or document layout. Schema-less
contracts, unsupported formats, external or dangling references, and schema `$id`
resource scopes raise an export-stage `CatalogError` with the contract key.
Loader-produced recursive schemas can be exported. Python converters and upgrades
remain application-owned. See the [export design](catalog-export-design.md) for
the artifact layout and reference rules. Filesystem overwrite and transaction
policies remain the caller's responsibility.

## Decode and upgrade explicitly

Configure `PayloadDecoder(catalog=..., bindings=..., upgrades=..., converter=...)`
before giving it to `NotehubClient(payloads=decoder)`. The decoder copies the
bindings, upgrade mapping, and cattrs converter. Client construction snapshots
the decoder again. Configure cattrs hooks before construction, especially hooks
used by nested generated converters. Stateful callable closures remain owned by
the application and should be treated as shared state.

```python
async with NotehubClient(token, payloads=decoder) as client:
    async for decoded in client.events.iter_decoded(project_uid, as_type=Reading):
        consume(decoded.body, decoded.raw, decoded.contract)
```

`client.payloads.decode(event, as_type=Reading)` also works with an event already
obtained elsewhere. It selects a source contract, copies the body, and structures
the bound source type with cattrs. If that type differs from `as_type`, it invokes
the direct upgrade keyed by `(contract.key, as_type)`. No migration graph is
searched. An unbound contract structures directly into the requested type.
`DecodedEvent[T]` retains the original event object in `raw`; callers should treat
it as read-only. Hooks receive a copied body.

Keep historical wire versions available, and give incompatible shapes or changed
units/meaning a new contract version. Additive optional fields can remain within a
compatible revision. A stable domain model can accept multiple source versions
through separately registered upgrades. JSON Schema defaults are annotations;
Python defaults and upgrades govern values produced by decoding.

`PayloadDecodeError` exposes `stage`, `contract`, and `paths`, preserving the
original failure as `__cause__`. Selection, missing body, structuring, missing
upgrade, and upgrade execution failures remain distinct. Errors are propagated
by typed iteration; there is no raw fallback or alternate-contract retry.
Formatted wrapper errors omit payload values. Underlying user/cattrs exceptions
may contain values, so choose deliberately whether to log chained tracebacks.

## Validate samples independently

Install `notehub-client[validate]`, then call
`catalog.validation.validate_sample(contract, body)` explicitly. It returns a
tuple of `ValidationIssue` records with instance path, schema path, and failed
keyword, omitting instance values. An empty tuple means no validation failures.
Invalid or unsupported schemas raise `CatalogError`.

The validator supports Draft 07 and the JSON Schema subset of AsyncAPI 3.1 schemas;
AsyncAPI discriminator semantics and other dialects are explicitly unsupported.
It does not fetch external references, insert defaults, or enforce `format`
annotations. Installing the extra never adds validation to reads or decoding.
Applications choose their sampling and CI policy. Compatibility comparison between
schema versions is deferred.

## Migrate process-wide outbound registrations

Replace module-level `@json_value.register` with a prepared Composer:

```python
from decimal import Decimal
from notehub_client.compose import Composer

composer = Composer()


@composer.json_value.register(Decimal)
def decimal_value(value: Decimal) -> object:
    return format(value, "f")


client = NotehubClient(token, composer=composer)
```

The six roles are `note_body`, `json_value`, `environment_values`,
`environment_value`, `notehub_identifier`, and `notehub_target`. Registered
handlers override structural `to_*` methods. Module-level adaptation functions
remain registration-free defaults. Standalone `resolve_*` helpers accept
`composer=...`; equivalent methods are available on Composer itself.

Each client gets a frozen registration snapshot. Later changes to the source
Composer do not affect existing clients. Dataclasses and attrs objects need an
explicit handler or structural method for writes; read-side cattrs support does
not imply outbound serialization. The JSON walker still rejects cycles,
unsupported values, non-string object keys, and non-finite numbers before sending.
