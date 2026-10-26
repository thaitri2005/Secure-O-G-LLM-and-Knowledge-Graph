# E3: Reproduction run of both ingestion paths, 25 October 2026

| | |
|---|---|
| **Date** | 25 October 2026 |
| **Question** | Do the published PDF bundle and the BSEE ingestion reproduce from scratch, and does the BSEE linked graph build cleanly? |
| **Requirement** | FR-02, FR-15, FR-16 (registry seed); specification gate G1 |
| **Input** | Main GDR registry, re-downloaded; BSEE snapshot of files dated 18 October 2026 |
| **Outputs** | Ignored, local: `data/interim/runs/eval_2026_10_25/`, `data/processed/local/bsee_wells/`, `data/processed/local/bsee_graph/` |
| **Status** | Passed |

A full run of both ingestion paths on the development laptop (Windows, CPU, locked environment). The metric definitions are in [E1](E1-pdf-ingestion-configuration.md) and [BSEE ingestion](../components/bsee-ingestion.md).

## Summary

| Check | Result |
|---|---|
| Unit tests | 106 passed, 1 skipped |
| Fresh PDF ingestion (main registry: AK-3, 56-32, 68-32) | **PASS**: re-downloaded, converted and chunked from scratch; byte-identical to the published bundle (all 9 `SHA256SUMS` entries match) |
| BSEE ingestion (snapshot of files dated 18 Oct 2026) | **PASS**: 0 errors; output identical across repeated builds |

## PDF ingestion

Fresh end-to-end run: 13 min 35 s, including PDF and model downloads. 372 chunks (237 text, 135 table), 0 validation errors, and 20 warnings. All 20 warnings are the documented case of a single table row that exceeds the 1,500-character budget on its own. Chunk SHA256 is `b3256ef6…037b9b`, as published.

Evaluation of named run `eval_2026_10_25`, using the default configuration on the same conversion:

| Metric | Value |
|---|---:|
| Quantity recall (drilling numbers and units, 335 total) | 0.9970 (334/335) |
| Substantive-page word recall: median / minimum | 0.9538 / 0.4423 |
| All-page word recall: median / minimum | 0.9661 / 0.2174 |
| Median word precision | 1.0000 |
| Gold table cell accuracy (main-report gold only) | 0.9885 |
| Canonical offset match / valid region boxes | 1.0000 / 1.0000 |
| Deterministic repeated chunking | Yes |
| Short text chunks / chunks ending mid-sentence (of 237 text chunks) | 116 / 116 |
| Scanned pages | 0 |

**Comparison with published results.** The quantity and substantive-recall figures equal those in [E1](E1-pdf-ingestion-configuration.md), so the published results are reproduced. Gold cell accuracy here (0.9885) is higher than the published 0.7037 because only the main-report gold table was scored: the AK-3 appendix conversion caches, which hold the other six gold tables, were not present for this run. Do not compare the two values directly.

Known weak spots are unchanged: dense directional-survey pages in 56-32 (pages 23–25) and the rotated daily form on 68-32 page 17.

## BSEE well-data ingestion

| Item | Value |
|---|---:|
| Boreholes (Gulf / Pacific / Alaska) | 57,453 (55,572 / 1,714 / 167) |
| Surface wells (first 10 API digits) | 39,518 |
| API-number changes | 587 |
| Malformed rows, duplicate API numbers, out-of-range coordinates | 0 |
| Boreholes with BSEE-withheld fields | 445 |
| Wells spanning several surface blocks | 2 |
| Parse time / validation time | about 15 s / about 1 min |

## BSEE linked graph (single source)

113,384 nodes and 398,263 edges, each edge citing its BSEE row, built in about 10 seconds with 0 missing endpoints:

- 57,453 Wellbore and 39,518 Well nodes, plus 8,742 Lease, 5,679 Block, 1,521 Field and 471 Operator nodes;
- 175 `RENUMBERED_FROM` links between boreholes.

Example finding: on lease G01608, 515 wellbores start on the lease but only 233 end in it, so many are drilled to neighbouring leases. The graph links records within BSEE.

## Not covered by this run

- The extended (2 reports) and AK-3 appendix (44 PDFs) registries were not rerun.
- No OCR run.
- Extraction, review and QA were evaluated only in the architecture prototype ([E4](E4-ak3-architecture-prototype.md); 15 AK-3 chunks, test build); production versions are M2 onward in the [development plan](../DEVELOPMENT_PLAN.md).
