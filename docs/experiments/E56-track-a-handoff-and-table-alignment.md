# E56 · K1 handoff, column alignment and scanned cell text

| Item | Value |
| --- | --- |
| Date | 23 November 2026 |
| Input | The 79-PDF scale corpus, eight original ZeroGen pages, the E53 scan suite and a second KGS scan |
| References | Pinned scale probes, ZeroGen's printed casing grid, E53's visually transcribed cells and a separate Chitwood calibration row |
| Runtime | Local Docling, PyMuPDF, PDFium, RapidOCR and Tesseract. Zero hosted model calls. |

## Handoff

QA checks each required PDF digest and its matching conversion cache before publishing the retrieval view. A companion manifest carries the package checksum and the view checksum. QA locks the output directory, withdraws the prior handoff at the start of a run and writes the companion manifest last. A failed validation returns exit code 1. `--release-only` produces a diagnostic ledger without a retrieval handoff. The GraphRAG reader used in the separate development checkout consumed the validated bytes and preserved `numeric_review`. It supported `GRAPHRAG_K1_ALLOW_RAW=1` for historical raw K1 comparisons. GraphRAG integration with this handoff is NOT EVALUATED on the integrated branch. [QA CLI](../../src/graph_builder/corpus/qa/cli.py) · [Handoff](../../src/graph_builder/corpus/qa/handoff.py)

| Real release check | Observed |
| --- | --- |
| New Crown with original PDFs and work cache | Exit 0 and a sealed view. GraphRAG reads 250 chunks and retains 13 cell warnings. |
| Checksum changed on a copy of a K1 release, reusing the successful QA output path | Exit 1. The previous view and manifest are withdrawn. |
| Original corpus missing | Exit 1. No retrieval handoff. |
| Explicit release-only diagnostics | Exit 0 for the valid K1 package. No retrieval handoff. |
| New Crown view paired with ZeroGen K1 | Rejected before indexing. |
| Active source rules with PyMuPDF unavailable | K1 preflight rejects the profile. |

The [English drilling corpus profile](../../configs/corpus/drilling_reports_en.json) resolves to the same settings as the 79-PDF benchmark corpus. K1 records the PDF reader versions and, when applicable, the secondary OCR runtime and model digests. [Setup](../components/corpus-ingestion.md)

## Extraction

Column alignment requires a native column inversion, unique ownership of all body columns and agreement from a second reader over the complete ruled grid. The native and printed headers must contain the same labels. The repair uses the source's printed positions and preserves values and blanks. For OCR, the ink rule activates on an existing cell with a corroborated printed prefix and blue ink below the printed line. The previous OCR value and original rectangle remain in `scan_repairs`. No document IDs or fixed report coordinates enter either rule. [Column alignment](../../src/graph_builder/corpus/column_alignment.py) · [Scan ink](../../src/graph_builder/corpus/scan_table_ink.py)

| Check | Before | E56 |
| --- | ---: | ---: |
| ZeroGen original page 16, header and body positions including blanks | 10/36 | **36/36** in K1 and retrieval |
| Other ZeroGen source cells already pinned for regression | 63/63 | **63/63** in K1 and retrieval |
| Scale corpus, exact phrases and cell probes | 1,271/1,271 and 47/47 | **1,271/1,271 and 47/47** |
| Scale corpus, ordered hourly intervals | 624/624 | **624/624** |
| OzAlpha approval matrix, annotated populated cells | 11/15 | **15/15**, with four repaired cells reproduced by QA |
| FORGE temperature track, annotated cells | 0/24 | **0/24** |
| Mobil logging-run and calibration regions, annotated cells | 0/28 | **0/28** |
| Chitwood neutron calibration, separate source gold | — | **0/8** |

The ZeroGen `Surface` row now has `197.9m` under `Casing Seat`. Its 26 populated header and body cells have source evidence. On the 79-PDF corpus, all six K1 JSONL files, retrieval text and cell evidence are byte-identical to E55. The K1 manifest changes with the new profile and runtime data. The local re-export from Docling cache took 108.4 seconds, and full QA took 44.8 seconds in this run.

Chitwood's separately transcribed grayscale scan is a distinct well and operator from Mobil. The held-out regions in both scans have no qualifying K1 grid. The ink rule improves already detected tables on color scans. Structured table discovery and reconstruction remain separate work for these grayscale layouts and the FORGE chart region. [Chitwood gold](../../configs/benchmarks/track_a_scan_cells_e56_chitwood.json) · [E53 scoring contract](E53-track-a-independent-scan-cell-qa.md)

## Reproduction

Run QA with the original corpus before loading the K1 retrieval pool. The `qa` command accepts `--out` for a distinct evaluation directory.

```sh
python -m graph_builder.corpus k1 "$CORPUS" --name e56 --models data/interim/ocr_models
python -m graph_builder.corpus qa "$CORPUS" --release "$RELEASE" --out "$QA" \
  --models data/interim/ocr_models --fidelity --crossrep --cell-evidence
python -m unittest discover -s tests
```

To reproduce the Chitwood result, use `scripts/run_track_a_scan_cells.py` and `scripts/benchmark_track_a_scan_cells.py` with `--gold configs/benchmarks/track_a_scan_cells_e56_chitwood.json` and the pinned source TIFF. To measure the extraction changes separately, set `repair_native_column_alignment` or `repair_scan_table_ink` to `false` in a copy of the K1 profile.
