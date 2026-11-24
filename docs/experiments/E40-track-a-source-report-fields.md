# E40 — Recovering missing daily drilling report fields from the source PDF

K1 recovers typed report fields when two distinct report identifiers establish that a source page contains a report header. It uses visible glyphs in the same row to pair a field with its value. Wider gaps require support from neighboring aligned fields. Conflicting well identifiers, report numbers or periods suppress recovery on that page. The exporter adds missing pairs with separate source rectangles for the label and value. New fields carry `verified: false` for review. [Implementation](../../src/graph_builder/corpus/report_fields.py)

## Results

The baseline uses the K1 configuration before this feature. Both K1 profiles share the same native Docling output for each corpus. Phrase scores use the QA retrieval view. Table-cell scores use the K1 grid with a pinned row anchor, column and value.

| Corpus and measure | Baseline | Source fields |
| --- | ---: | ---: |
| E38 · 79 PDFs, 229 pages, five report families · exact phrases | 856/1,271 (67.3%) | 1,266/1,271 (99.6%) |
| E38 · exact table cells | 43/47 | 43/47 |
| E38 · numeric occurrences matched | 47,056/48,072 | 47,600/48,072 |
| E38 · repeat numeric occurrences above source count | 10,937 | 11,338 |
| Fresh Volve · 24 input PDFs, 40 pages, four wells · exact phrases | 132/157 (84.1%) | 157/157 (100%) |
| Fresh Volve · numeric occurrences matched | 4,059/4,168 | 4,130/4,168 |
| Fresh Volve · repeat numeric occurrences above source count | 76 | 87 |

Every previously matched phrase and table-cell probe remains matched. Fresh Volve gains span all four wells. The exact table score includes 31 of 31 casing probes and 12 of 16 time-log probes. Structural validation passed for all four releases. Table/chunk consistency findings stayed at one in E38 and nine in Volve. The benchmark independently checked the rectangles of every added field with PyMuPDF. All 832 rectangles in E38 and all 50 in Volve matched. The transfer gate requires disjoint source hashes and report families, a held-out gain, retention of the existing probes and table consistency, and matching source rectangles. [E38 sources and probes](../../configs/benchmarks/track_a_scale_holdout.json) · [Fresh Volve sources and probes](../../configs/benchmarks/track_a_volve_fresh.json)

The fresh input was frozen before scoring the candidate. It uses four Volve wells absent from E39 and a different report family from the five E38 families. It shares the WITSML PDF layout seen in E39. The Volve inputs use the catalog IDs derived from their filenames and hashes. K1 classifies them as `other` and uses the dated report identity on the source page to admit recovery. The holdout probes measure text-layer headers. The numeric repeat count measures occurrences on each page, including repeated representations of a number.

Five frozen probes on Myrtle Basin pages 38, 41, 44, 47 and 50 contain the visible report number followed by a clipped `16` from the PDF text layer. The visible report numbers are `13`, `14`, `15`, `16` and `17`. The table above uses the original frozen probes. The four time-log misses arise from the Palm Valley page 13 header being treated as data and the absent standalone time-log grid on page 30. [E38 table analysis](E38-track-a-scale-benchmark.md)

## Runtime

| Corpus | K1 before | K1 after | QA before | QA after |
| --- | ---: | ---: | ---: | ---: |
| E38 | 23.3 s | 36.0 s | 8.0 s | 8.2 s |
| Fresh Volve | 2.6 s | 4.4 s | 0.8 s | 0.8 s |

Times are wall-clock seconds on the same already-converted corpus. Cold native conversion of the 40 Volve pages took 112.2 wall seconds and 341.8 CPU seconds with two workers. Source-field recovery runs locally in K1 and incurs zero billed model or OCR API calls. The test suite ran 1,213 tests with 16 skipped and zero failures.

## Reproduction

Prepare the E38 native corpus as described in [E38](E38-track-a-scale-benchmark.md). Build the Volve bundles with the pinned manifest and process them into their own corpus. Docling accepts either the local model cache or the artifact directory specified by `DOCLING_ARTIFACTS_PATH`.

```sh
python scripts/prepare_volve_ddr_holdout.py \
  --manifest configs/benchmarks/track_a_volve_fresh.json --pdf-dir data/raw/track-a-volve-fresh
python scripts/benchmark_track_a_scale.py \
  --manifest configs/benchmarks/track_a_volve_fresh.json --pdf-dir data/raw/track-a-volve-fresh \
  --out data/interim/track-a-volve-fresh-natural --workers 2
```

```sh
python scripts/benchmark_header_transfer.py --only-profile source_fields \
  --manifest configs/benchmarks/track_a_scale_holdout.json --pdf-dir data/raw/track-a-scale \
  --seed data/interim/track-a-scale/corpus --out data/interim/track-a-source-fields/final-regression
python scripts/benchmark_header_transfer.py --only-profile source_fields \
  --manifest configs/benchmarks/track_a_volve_fresh.json --pdf-dir data/raw/track-a-volve-fresh \
  --seed data/interim/track-a-volve-fresh-natural/corpus --out data/interim/track-a-source-fields/natural-fresh \
  --against data/interim/track-a-source-fields/final-regression/results.json
```

`results.json` records coverage, timings, QA findings and the rectangle audit. The second invocation writes `transfer_gate.json` and exits with status 1 if the candidate fails.
