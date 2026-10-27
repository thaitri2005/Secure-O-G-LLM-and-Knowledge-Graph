# E6: BSEE well data through the generic structured-data importer

| | |
|---|---|
| **Date** | 27 October 2026 |
| **Question** | Can the mapping-driven importer replace the BSEE-specific adapter and graph builder without changing a single record, node or edge count? |
| **Requirement** | FR-15, FR-16 (registry seed); specification §5.7 |
| **Input** | BSEE snapshot of files dated 18 October 2026 (the same verified ZIPs as [E3](E3-reproduction-run-2026-10-25.md)) |
| **Code** | [`graph_builder.datasets`](../../src/graph_builder/datasets/) with [`configs/datasets/bsee_wells.mapping.json`](../../configs/datasets/bsee_wells.mapping.json) |
| **Outputs** | Ignored, local: `data/processed/local/datasets/bsee_wells/` |
| **Status** | Passed |

## Method

The BSEE layouts, withheld markers, derived keys, checks and graph rules were written as one mapping file. The adapter's Python code was not used. The importer reused the cached ZIPs, verifying each against the recorded snapshot digest:

```powershell
python -m graph_builder.datasets run --mapping configs/datasets/bsee_wells.mapping.json
```

The output was then compared with the adapter's bundle (`data/processed/local/bsee_wells/`) and the graph builder's summary (`data/processed/local/bsee_graph/summary.json`). Records were matched by source file and row number. Every field was compared except the bundle-specific `source` and `table` wrappers and three helper fields the mapping adds: `surface_block_key`, `bottom_block_key`, `previous_api_digits`.

## Results

| Check | Generic importer | Dedicated adapter and graph builder |
|---|---:|---:|
| Borehole records, identical in every field and source digest | 57,453 | 57,453 |
| API-number change records, identical | 587 | 587 |
| Nodes: Wellbore / Well / Lease / Block / Field / Operator | 57,453 / 39,518 / 8,742 / 5,679 / 1,521 / 471 | same |
| Edges: HAS_WELLBORE / OPERATED_BY / SURFACE_IN_BLOCK / BOTTOM_IN_BLOCK | 57,453 each | same |
| Edges: BOTTOM_ON_LEASE / SURFACE_ON_LEASE / BOTTOM_IN_FIELD / RENUMBERED_FROM | 57,447 / 57,411 / 53,418 / 175 | same |
| Errors; boreholes with withheld fields | 0; 445 | 0; 445 |
| Bundle validation (digests, generated schemas, unique IDs, edge endpoints) | pass | – |

Differences:

- The generic importer does not produce the adapter's `wells.jsonl` grouping or its warning about the 2 wells whose boreholes start in different surface blocks. The Well nodes and HAS_WELLBORE edges carry the same grouping.
- Nodes carry the provenance of their first record. Wellbore nodes do not collect `former_api_numbers`: renumbering is expressed by the 175 RENUMBERED_FROM edges, and unmatched previous numbers stay in the API-change records.

## Interpretation

A new dataset needs a mapping file, not code. `python -m graph_builder.datasets infer FILE` drafts one from a CSV or Excel sample. The BSEE-specific modules stay in the repository because earlier experiments reference them; new structured sources should use the importer.

## Later validation findings

[E9](E9-repository-review.md), 27 October, found that the generic CLI validates the bundle after installation and reproduced duplicate generated record IDs when no natural key was configured. Duplicate headers can also discard values, and replacement is not an atomic pointer switch. These findings do not change E6's successful BSEE comparison; they limit the generic importer's readiness for arbitrary/shared-service inputs. Fixes remain open.
