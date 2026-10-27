# Structured-data import (`graph_builder.datasets`)

**Delivery scope:** domain-agnostic core, one English-first oil-well application. This guide records implemented component behavior; existing Vietnamese OCR options remain available for reproduction. Oil-specific identifiers and mappings belong to the oil-well profile/adapters. See [core/profile boundary](../PROJECT_DESIGN.md#44-core-and-domain-profile-boundary).

This guide describes the **implemented generic importer** for tabular data. One mapping file describes:
- the source files;
- how to parse them into typed records;
- the checks to apply;
- the nodes and edges to build.

Every record and edge cites its source file, its SHA256 and its row. BSEE well data is imported through it, and reproduces the dedicated adapter exactly ([E6](../experiments/E6-generic-import-bsee.md)).

## Commands

```powershell
python -m graph_builder.datasets infer D:\data\gieng.xlsx > configs/datasets/gieng.mapping.json   # draft a mapping from a sample
python -m graph_builder.datasets run --mapping configs/datasets/gieng.mapping.json                 # fetch, import, validate
python -m graph_builder.datasets fetch --mapping configs/datasets/bsee_wells.mapping.json --refresh
python -m graph_builder.datasets validate --output data/processed/local/datasets/bsee_wells
```

`infer` detects the encoding, the delimiter, a header row and column types: integer, decimal (including Vietnamese `1.234,5`), date in common Vietnamese and ISO formats, boolean (`có`/`không`), string. It suggests a unique key. Review the draft before importing, then add checks and graph rules.

## Mapping file

| Part | Content |
|---|---|
| `dataset_id`, `title`, `license`, `allowed_hosts` | Identity, terms, and the only hosts downloads may use |
| `sources[]` | `source_id`, `table`, exactly one of `url` or `path` (relative to the mapping file), optional `member` inside a ZIP, optional pinned `sha256`, optional `constants` added to every record |
| `tables.<name>.layout` | `type`: `csv` (any delimiter, `header`, `encoding` or `auto`, `skip_rows`), `xlsx` (`sheet`, `header`) or `jsonl` |
| `tables.<name>.columns[]` | `name`, `type` (`string`, `integer`, `decimal`, `date`, `datetime`, `boolean`), optional `source` (header name), `required`, `pattern`, `values`, `min`/`max`, `formats` for dates, `decimal_mark`/`thousands`; or `split` for fixed-width parts of one cell |
| `withheld_chars`, `warn_withheld` | Values made only of these characters (for example BSEE's `#`) become `null` and are listed in `withheld`, separate from blanks |
| `derived` | `slice`, `strip_leading_zeros`, `digits`, `upper`, `lower`, `template` |
| `id`, `key` | Record ID template (`{field}`, `{_source_id}`, `{_row}`) and unique key fields |
| `checks[]` | `range`, `compare` (left op right) and `reference` (value must be a key of another table), each with `error` or `warning` severity |
| `graph.nodes[]`, `graph.edges[]` | Label or type, source table, ID templates, properties, `skip_values` for placeholders, `require_existing`, `not_self` |
| `error_policy.max_errors` | Default 0: any malformed row or failed error check stops the import and writes nothing. A higher budget writes the bad rows to `rejects.jsonl` |

[`configs/datasets/bsee_wells.mapping.json`](../../configs/datasets/bsee_wells.mapping.json) is a complete example. It uses headerless quoted CSV in ZIPs, fixed-width split columns, withheld markers, derived keys, all three check types, and a graph of six node labels and eight edge types.

## Behaviour

- **Snapshots:** downloads go to `data/raw/<dataset_id>/` and are recorded in `snapshot.json` (URL, bytes, SHA256, `Last-Modified`, time). A cached file is reused only if its digest matches. A pinned `sha256` that no longer matches stops the import, so a publisher's new version is never taken silently.
- **Encodings:** `auto` tries UTF-8 (with or without BOM), UTF-16, Windows-1258 (Vietnamese) and Windows-1252. Text is normalized to NFC, so tone marks stored as combining characters compare equal to precomposed ones.
- **Scale:** record processing uses streaming and temporary SQLite keys/nodes. XLSX ZIP members may be read fully into memory; this is not a bound on all input memory. Output is staged, then installed after import-level error checks. The CLI's full bundle validation runs afterwards; validation-before-publication remains an open fix.
- **Outputs**, in `data/processed/local/datasets/<dataset_id>/` by default:
  - `records/<table>.jsonl`;
  - `nodes.jsonl` (nodes carry their first record's evidence) and `edges.jsonl` (one per row, with evidence);
  - `schemas/<table>.schema.json`, generated from the mapping;
  - `rejects.jsonl`;
  - `summary.json` (counts, warnings with examples, null and withheld counts per field, source snapshot);
  - `SHA256SUMS`.

## Limitations

- Replacing a bundle uses two renames and can leave the published path absent on interruption. Use a fresh output directory while the immutable-release/pointer fix remains open.
- Optional natural `key` checks do not independently enforce unique generated `record_id` values during import. A duplicate-ID bundle can be installed before post-import validation reports it ([E9](../experiments/E9-repository-review.md)).
- Duplicate/empty CSV or XLSX header names are not rejected; duplicate names can silently discard a value. Inspect headers before importing until this is fixed.
- Download size caps, pre-request redirect checks and enforced parser CPU/RAM/disk budgets remain planned. The ZIP-member size check alone does not provide these guarantees.

- One sheet per table for Excel. Formulas are read as their cached values.
- No aggregation across rows (for example collecting all previous numbers onto one node); express such links as edges.
- Fixed-width text files without delimiters need a `split` column over a one-column layout.
- Node properties come from the first row that creates the node. Conflicting values in later rows are not reported yet.
