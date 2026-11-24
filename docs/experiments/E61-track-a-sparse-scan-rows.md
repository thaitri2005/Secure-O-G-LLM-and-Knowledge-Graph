# E61 · Scan tables with open rulings

24 November 2026

The default closed-grid reader missed two calibration rows on original Kansas well-log scans. The printed columns are separated by gaps in recurring horizontal rules. The fallback finds those recurring gaps, discards a candidate cut that crosses a located word, and estimates a small correction for page skew. Both RapidOCR and Tesseract must support the recovered text. Ink without a corroborated reading is recorded as `ocr_unreadable` so cell QA can send it for review. [Implementation](../../src/graph_builder/corpus/scan_bands.py)

K1 can replace a native scan table if the reconstructed table preserves the full token inventory and its source region matches. For the region comparison, K1 can include trailing blank ruled space that was captured by the original table. The published table region covers the verified headings and data. The fallback takes its geometry from the image and uses the same procedure across documents.

## Evidence

The Mobil and Chitwood references were visually transcribed from the original TIFFs before E61. The evaluation checked the source hash, compared the embedded PDF image against the pinned TIFF window and verified the exported release checksums. Positional scoring compares the cells in a single annotated row by column in its source region. Strict scoring additionally requires the exact printed row label. Cell QA repeats the extraction from the source PDF and records the reasons for unresolved cells. The visual references provide the independent accuracy check. [Mobil reference](../../configs/benchmarks/track_a_scan_cells_e53.json) · [Chitwood reference](../../configs/benchmarks/track_a_scan_cells_e56_chitwood.json) · [Independent scorer](../../scripts/benchmark_track_a_scan_cells.py)

| Scan | Exact body cells by position, off → on | Strict body score, off → on | Cached K1, off → on | Source QA, off → on |
| --- | ---: | ---: | ---: | ---: |
| Mobil 12-1 calibration | 0/8 → 5/8 | 0/8 → 0/8 | 0.7 s → 35.3 s | <0.1 s → 34.3 s |
| Chitwood 12 calibration | 0/8 → 6/8 | 0/8 → 6/8 | 8.1 s → 63.0 s | <0.1 s → 56.8 s |

All 11 emitted body values match the TIFF at the annotated column positions. The Mobil row lacks its printed key under strict scoring, and only one of its eight headings matches the full annotation exactly. The Chitwood row has two unresolved body cells. The separate sideways logging panel on Mobil still has no exported table in its annotated region.

A generated circulation sheet with a different column count, typeface and measurements checked that the fallback can also correct existing OCR cell assignments. Its contents were set before extraction. Two additional well-log raster crops served as controls for spurious tables. The 79-PDF benchmark checked existing native PDFs and does not measure scan recall. [Stone raster source](https://github.com/GeoLarryLai/pyLogDigitizer/tree/f7d58ff4da57f830dc510457d3281148d7311a4f/example_data/STONE_5-19_15-055-22611) · [USA A-16 raster source](https://github.com/GeoLarryLai/pyLogDigitizer/tree/f7d58ff4da57f830dc510457d3281148d7311a4f/example_data/USA_A_16_15-055-20536)

The circulation sheet improved from zero to all six body positions and retained all six exact headings. Source QA replay corroborated all 12 cells. Both raster controls continued to produce zero tables. The 79 native PDFs retained identical K1 records for 229 pages, 947 tables and 2,297 chunks. Their cell-evidence and retrieval records were byte-identical, and the validator reconstructed all 229 pages.

The fallback remains an explicit K1 option. Verification on calibration strips supports this layout, and original scans with additional layout families remain necessary to measure transfer. Inference and QA run locally using the existing OCR models. Reported times exclude the initial document conversion.

## Reproduction

Convert each input once using the [English drilling profile](../../configs/corpus/drilling_reports_en.json). Use the same conversion cache and local OCR weights for both runs. The default K1 profile already enables `recover_scan_grids`, which is required for this fallback. Run the source QA and score each release against its corresponding TIFF reference.

```sh
python -m graph_builder.corpus k1 "$CORPUS" --name sparse-off --no-recover-sparse-scan-rows
python -m graph_builder.corpus k1 "$CORPUS" --name sparse-on --recover-sparse-scan-rows
python -m graph_builder.corpus qa "$CORPUS" --release "$RELEASE" --out "$QA" --crossrep --fidelity --cell-evidence
python -m unittest discover -s tests -p test_scan_bands.py
```
