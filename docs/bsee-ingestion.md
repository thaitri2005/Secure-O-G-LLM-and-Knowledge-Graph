# BSEE well-data ingestion

This document describes the **implemented structured-data adapter** for the BSEE Data Center well files. Why this dataset was chosen, and what it contains, is in [Development focus and data sources](DATA_SOURCES.md). How its records will become graph knowledge is in [design §5.7](PROJECT_DESIGN.md#57-structured-well-data).

The adapter uses only the Python standard library plus `jsonschema` for output validation. It adds no dependencies to the lock file.

## Commands

```powershell
python -m graph_builder.ingestion.bsee run                       # fetch (or verify) + parse + validate
python -m graph_builder.ingestion.bsee fetch [--refresh]         # download, or verify the local snapshot
python -m graph_builder.ingestion.bsee parse                     # rebuild the bundle from the snapshot
python -m graph_builder.ingestion.bsee validate                  # check an existing bundle
python -m graph_builder.ingestion.bsee show --api 1772140041     # print the well, boreholes and API changes
```

| Option | Default | Meaning |
|---|---|---|
| `--config` | `configs/datasets/bsee_wells.json` | Dataset configuration: files, regions, coordinate datums, ZIP member names |
| `--output` | `data/processed/local/<dataset_id>/` | Bundle directory (ignored by Git) |
| `--refresh` | off | Download again even when a verified snapshot exists |
| `--api` | – | `show` only: at least the first 10 digits of an API number |

Exit code 0 means the bundle was written and validated. Any malformed row or failed check exits 1, and the previous bundle is left untouched.

## Stages

1. **fetch.** Downloads each configured ZIP over HTTPS from `www.data.bsee.gov` only; redirects to other hosts are refused. The file is written to `.part` first. The adapter checks that the expected member exists and is below 200 MiB, then moves the file into `data/raw/<dataset_id>/<file_id>.zip`. `snapshot.json` records the URL, size, SHA256, `Last-Modified` and retrieval time. Later runs verify the local file against the snapshot instead of downloading again, so a tampered or truncated file fails. If a file entry in the configuration pins `sha256` (and optionally `bytes`), a download that differs fails.
2. **parse.** Streams the CSV member. The files are quoted and header-less, and values keep their fixed-width padding. Each row is mapped through the published record layout in [`bsee_layouts.py`](../src/graph_builder/ingestion/bsee_layouts.py) and converted to typed values. Any column-count, API-number, integer, decimal or date mismatch is an error.
3. **check.** Cross-record rules (below). Errors stop the run before anything is written; warnings are counted, and five examples of each are kept in `summary.json`.
4. **write.** Stages the full bundle in `<output>.partial/`, then replaces the previous bundle. It refuses to replace a directory that is not a BSEE bundle, meaning one without `summary.json`.
5. **validate.** Checks every output line against its JSON schema, compares digests with `SHA256SUMS`, checks record IDs for uniqueness, and confirms that `wells.jsonl` covers every borehole exactly once.

## Output bundle

| File | One record per | Key fields |
|---|---|---|
| `boreholes.jsonl` | Borehole (12-digit API number) | All 37 layout fields, typed; `well_api10`; `coordinate_datum`; `withheld`; `source` |
| `api_changes.jsonl` | Row of the API Number Changes files | Current and previous API number, activity date, names and locations |
| `wells.jsonl` | Surface well (first 10 API digits) | Boreholes with names and statuses; surface area/blocks; previous API numbers; `source_record_ids` |
| `summary.json` | Bundle | Snapshot (URLs, SHA256, dates), counts per region, code distributions, withheld-field counts, warnings with examples, output digests |
| `SHA256SUMS` | Bundle | Digests of the four files above |

Schemas: [`bsee_borehole`](../schemas/bsee_borehole.schema.json), [`bsee_api_change`](../schemas/bsee_api_change.schema.json), [`bsee_well`](../schemas/bsee_well.schema.json). Rebuilding from the same snapshot produces byte-identical files. All text is UTF-8 with LF line endings.

### Provenance

Every borehole and API-change record carries:

```json
"source": {"dataset_id": "bsee_wells", "file_id": "borehole_gulf",
           "url": "https://www.data.bsee.gov/Well/Files/5010delimit.zip",
           "sha256": "1bf9abb7…", "member": "5010.txt", "row": 1}
```

`row` is the 1-based line in the ZIP member. Together with the file SHA256 it identifies the exact source row, which is the dataset equivalent of a PDF page and character span. Record IDs are `bsee:borehole:<api12>` and `bsee:well:<api10>`, both stable across snapshots, and `bsee:<file_id>:<row>` for API changes, which have no natural key.

### Value conventions

| Situation | Representation |
|---|---|
| Padded text (`"  001 "`, `"S00538    "`) | Stripped (`"001"`, `"S00538"`) |
| Blank value | `null` |
| Value withheld by BSEE (`#####`, `*****`) | `null`, **and** the field name is listed in `withheld` |
| Dates `YYYYMMDD` and `MM/DD/YYYY` | ISO `YYYY-MM-DD`; unpadded or impossible dates are errors |
| Depths and elevations | Integers in feet: `rkb_elevation_ft`, `bh_total_md_ft`, `tvd_ft`, `water_depth_ft` |
| Block-line distances | Integers without a unit suffix: BSEE's layout does not state the unit (presumed feet) |
| Coordinates | Decimal degrees with the record's `coordinate_datum` (NAD27 in the Gulf, NAD83 in the Pacific and Alaska); never converted |
| Codes (status, type, class, district) | Verbatim. No meanings are attached until a verified BSEE code table is added. |
| Combined delimited columns | Split by the fixed-width layout: `03707N07080W` becomes `surface_ns_distance` 3707, `surface_ns_code` N, `surface_ew_distance` 7080, `surface_ew_code` W |

## Checks

| Kind | Rule | Snapshot of 18 Oct 2026 |
|---|---|---|
| Error | Row does not match the layout (column count, type, date, API shape, combined-column width) | 0 |
| Error | Same API number appears twice (across all files) | 0 |
| Error | Latitude outside ±90 or longitude outside ±180 | 0 |
| Warning | Borehole has withheld fields | 445 |
| Warning | Surface well spans several regions or surface area/blocks | 2 |
| Warning | TVD greater than measured depth | 0 |
| Warning | Spud date after total-depth date | 0 |
| Warning | API change refers to an unknown borehole | 0 |

## Linked graph

`python -m graph_builder.graph.bsee build` turns the bundle into a property graph in ignored `data/processed/local/bsee_graph/`: `nodes.jsonl`, `edges.jsonl` and `summary.json`. Every edge carries `evidence`: the record ID, file, file SHA256 and row it came from. `show <node-id>` lists a node's properties and its links in both directions:

```powershell
python -m graph_builder.graph.bsee build
python -m graph_builder.graph.bsee show well:1772140041      # also wellbore:…, lease:G01608, block:SP-60, operator:00276, field:SP060
```

| Edge | From → to | Count (18 Oct 2026 snapshot) |
|---|---|---:|
| `HAS_WELLBORE` | Well → Wellbore | 57,453 |
| `OPERATED_BY` | Wellbore → Operator (number only) | 57,453 |
| `SURFACE_ON_LEASE` / `BOTTOM_ON_LEASE` | Wellbore → Lease | 57,411 / 57,447 |
| `SURFACE_IN_BLOCK` / `BOTTOM_IN_BLOCK` | Wellbore → Block (zero padding removed) | 57,453 / 57,453 |
| `BOTTOM_IN_FIELD` | Wellbore → Field code | 53,418 |
| `RENUMBERED_FROM` | Wellbore → its former Wellbore record (API change) | 175 |

Nodes: 57,453 Wellbore, 39,518 Well, 8,742 Lease, 5,679 Block, 1,521 Field, 471 Operator. Placeholders are not linked: `NOLEASE` (48 links skipped), and the field code `WILD`, read as a wildcat outside a named field (4,035 skipped). Reading `WILD` as wildcat is BSEE convention rather than a published code table. Former API numbers that match no borehole are kept as `former_api_numbers` on the wellbore. The build checks that every edge endpoint exists and every wellbore has exactly one well; it takes about 10 seconds.

These links stay within BSEE, by design ([design §5.7](PROJECT_DESIGN.md#57-structured-well-data)).

## Performance

On the development laptop, verifying the snapshot and parsing about 58,000 rows takes about 15 seconds. Schema validation of the roughly 97,000 output records takes about one minute. The download is about 4 MB, and the bundle is about 100 MB, so it is not committed.

## Extending the adapter

To ingest another BSEE file (for example directional surveys):

1. Read its record-layout page and add a layout tuple to `LAYOUTS` in `bsee_layouts.py`. Combined delimited columns are tuples of `(name, width, kind)` parts.
2. Download one file and profile it before trusting the layout: check column counts, blank and withheld markers, date formats and duplicate keys.
3. Add its file entries to the dataset configuration, decide on a record ID, add a schema `schemas/bsee_<table>.schema.json` and an entry in `OUTPUTS`, and extend the cross-record checks if the table references boreholes.
4. Add a synthetic fixture to `tests/test_bsee.py`.

Directional-survey ZIPs are 100–140 MB per region. Filter them by API number while streaming instead of loading them whole.

## Limitations

- Code meanings, operator names and field names are not resolved; they need BSEE lookup tables that are not ingested yet.
- The adapter keeps one snapshot. Comparing two snapshots (added, changed and removed boreholes) is planned work for the review step ([design §5.7](PROJECT_DESIGN.md#57-structured-well-data)).
- It is a CLI, not a service. The upload, authorization and job-queue requirements of the target design still apply.
- BSEE's terms are a disclaimer rather than an open license. Do not commit raw or derived files without confirming redistribution terms.
