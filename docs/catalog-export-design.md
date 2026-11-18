# Portable catalog export design

The pure export bundle described here is implemented in `catalog.exporting`.
It produces self-contained artifacts suitable for `loads(..., read_document=...)`
and preserves contract selection and validation behavior without the original
files or Python binding implementations. Filesystem convenience APIs remain
deferred; this document records the design and its acceptance gates.

## Preserved data and scope

[Contract](../src/notehub_client/catalog/models.py) retains identity, selector,
binding name, schema format, and a copied JSON schema. The
[loader](../src/notehub_client/catalog/loading.py) resolves message references and
bundles document-relative schema references into standalone `definitions`.
It does not retain AsyncAPI channels, operations, document metadata, YAML comments,
or original schema resource scopes. `message_ref` is a source locator, not a
reference to a source document held by the catalog.

This is normalized export, not source editing. Do not fetch the original
`message_ref`, preserve it as an output link, or imply byte-for-byte round trips.

## Artifact boundary

The pure `export_artifacts(catalog)` function in `catalog.exporting` returns an
immutable `CatalogArtifacts` value with `manifest: str` and
`documents: Mapping[str, str]`. Documents contain JSON text under relative names.
The in-memory usage is:

```python
artifacts = export_artifacts(catalog)
restored = loads(artifacts.manifest, read_document=artifacts.documents.__getitem__)
```

These names are exposed from `notehub_client.catalog`. Avoid
calling the bundle `dumps`: a string alone cannot carry the companion documents,
and a file-writing callback would make the result harder to inspect before
writing. Defer `dump` and filesystem policy to a separate batch. Applications can
explicitly write the manifest and documents with their existing storage tools.

Generate one `messages.json` document with AsyncAPI version `3.1.0`, minimal
generated `info`, and `components.messages`. Assign keys `contract0`, `contract1`,
and so on in catalog iteration order. Each manifest reference becomes
`messages.json#/components/messages/contractN`. IDs and versions remain values,
never filenames or pointer segments.

Retain catalog order: selection chooses the first matching family. Emit metadata
in fixed order and produce deterministic text for the same catalog. Do not sort
contracts by ID, infer a latest version, or deduplicate schemas in this batch.

## Representability and reference relocation

Validate the complete catalog before returning artifacts. Raise
`CatalogError("export", ...)` with the affected contract key and a sanitized
reason; never silently omit a contract or weaken it.

- Require an attached schema. The manifest requires `message_ref`, and loading
  that message always attaches a schema. Replacing an absent schema with `true`
  changes the model. A future manifest revision can represent absence explicitly.
- Support the same two schema formats as the loader. Preserve `schema_format`
  using an explicit `schemaFormat`/`schema` payload wrapper, including boolean
  schemas. Reject unsupported formats before producing a bundle.
- Preserve binding names only. Python types, converters, upgrades, and decoder
  state are not members of `Catalog` and do not belong in artifacts.
- TOML has no null scalar. For a discriminator with `value=None`, emit the
  discriminator and omit `value`; the loader's default restores explicit null
  matching. Preserve empty discriminator pointers, false, zero, and empty strings.
- Relocate schema-location `$ref` values from standalone fragments to the generated
  document. For `contractN`, the schema root is
  `/components/messages/contractN/payload/schema`. A root reference `#` targets
  that root; `#/definitions/node` targets its child. Decode URI fragments before
  validating JSON Pointers, then encode the relocated fragment without changing
  pointer escape sequences.
- Reuse [map_schema](../src/notehub_client/catalog/schema.py) so reference-looking
  values inside `const`, `enum`, examples, and defaults remain literal data.
  Reject external references and non-pointer anchors. Resolve local references
  against the source schema to reject dangling references.
- Reject programmatically supplied schema resource scopes (`$id`) in this first
  profile rather than silently stripping their identifiers. Loader-produced
  schemas already remove those scopes. Supporting resource scopes needs its own
  reference-resolution design.

An empty catalog produces a version-1 manifest with no contracts and an empty
documents mapping. Export does not read documents, open files, perform network
requests, or validate sample payloads.

## Implementation slices and acceptance gates

1. Add the immutable artifact value and pure renderer. Round-trip ordered
   contracts, opaque versions, binding names, both schema formats, boolean schemas,
   and an empty catalog through the loader with an in-memory reader.
2. Cover TOML escaping and all selector scalar cases, especially null, false
   versus zero, empty pointers, Unicode, quotes, and control characters. Compare
   `Catalog.resolve()` results for matching, nonmatching, and ambiguous events.
3. Cover root recursion, mutual recursion, escaped pointer keys, percent-encoded
   fragments, and literal `$ref` data. Compare `validate_sample()` results for
   accepted and rejected payloads. Reloading can rebundle definitions, so structural
   schema equality is not the round-trip criterion.
4. Reject absent schemas, unsupported formats, external or dangling references,
   and resource scopes with export-stage errors. Verify catalog immutability and
   deterministic repeated rendering. Assert diagnostic keys without logging schema
   or payload values.
5. Add public exports, an in-memory round trip, and a deliberate multi-file writing
   example. Keep filesystem transactions, fsspec writes, overwrite policy, and
   `dump` convenience APIs as separate reviewed work.

Use the existing catalog tests and optional validation dependency. This batch
does not change selection precedence, payload decoding, simulation, or the
loader's accepted manifest version.
