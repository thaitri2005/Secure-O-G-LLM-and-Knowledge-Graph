# E53 · Independent cell scoring for scanned drilling tables

E53 freezes visual annotations for 67 populated body cells, 13 printed header cells and five known blank cells across four tables or chart regions. The transcription was made from source pixels before the evaluation outputs were opened. It was reviewed by a single annotator. The original source hashes, case coordinates, row keys, units and exclusions are in the gold file. [Gold annotations](../../configs/benchmarks/track_a_scan_cells_e53.json)

The development cases are a printed temperature track in the original Utah FORGE mud log and a signed approval matrix on OzAlpha-1 page 5. The two holdout cases are from a Kansas Geological Survey scan for Ashland Oil & Refining's Mobil 12-1. The upper 1,750 pixels of the original TIFF were embedded in one PDF page at the original 300 DPI. The TIFF has a sideways logging-run panel and an upright calibration table. The benchmark retains both orientations and verifies the embedded pixels against the pinned image. The KGS scan is fetched from a commit-pinned mirror. The official URL returned HTTP 403 in this environment. [KGS source details](https://raw.githubusercontent.com/GeoLarryLai/pyLogDigitizer/f7d58ff4da57f830dc510457d3281148d7311a4f/example_data/SOURCES.txt)

## How the benchmark scores cells

The scorer consumes the published K1 tables and the frozen visual transcription. It does not load OCR, extraction rules or the extraction evidence sidecar. It validates source identity, raster page identity and release checksums. It selects a table by page and region before inspecting any cell text. No match counts as a missing table. Multiple matches are recorded as ambiguous. Once a table is selected, the scorer aligns unique row keys and checks cell content at the original column indices, along with physical row order and any annotated header cells. For a measurement used as a row key, the numeric part aligns the row while the body score still checks the unit. Whitespace, case and equivalent printed glyphs are normalized. Feet, inches, °F and °C remain distinguishable. [Independent scorer](../../scripts/benchmark_track_a_scan_cells.py)

A populated source cell is either exact, missing or incorrect at its source row and column. A nonempty prediction in a known blank, duplicate or unexpected row also counts against precision. A wrong-column or wrong-row label indicates that the value matches a different position in the reference and should be checked in the source. For the approval matrix, the merged recommender body region is explicitly outside the scope because a handwritten replacement crosses adjacent rows. The scorer includes the five printed headers, the printed names and the visibly blank revision cells. For FORGE, the scorer includes eight labelled MD ticks with printed in/out temperatures. Plot curves and surrounding tracks are outside the scored region.

## Actual E52 baseline

All three K1 releases passed structural QA. The source-cell score independently identified the following misses.

| Source case | Split | Correct body cells | Exact rows | Result |
| --- | --- | ---: | ---: | --- |
| FORGE temperature track, 200–900 ft | Development | 0/24 | 0/8 | No structured grid at the annotated region |
| OzAlpha-1 approval matrix | Development | 11/15 | 1/5 | Four Author cells include extra marks or text from signatures. All five headers and five blank revision cells matched |
| Mobil 12-1 logging run | Holdout | 0/20 | 0/10 | No structured grid at the annotated region |
| Mobil 12-1 Gamma Ray calibration | Holdout | 0/8 | 0/1 | No structured grid at the annotated region |

Development precision was **73.3%** and recall was **28.2%** for populated body cells. Holdout recall was **0/28** and holdout precision is undefined because no qualifying cell predictions were made. The Mobil strip contained OCR prose in the release. The table score is a structured-export measure. The sample is two development sources and one independent holdout source. It establishes these specific coverage gaps.

A fresh run through the documented commands reproduced the same candidate grids, cell errors and totals. The three-page FORGE PDF took 284.6 seconds through conversion, K1 and QA on the benchmark host. Most of that time was spent on the scan-strip OCR fallback during K1 export.

## Deliberate error checks

The checks begin with the visually transcribed real FORGE and OzAlpha grids. Moving a fault through this scoring path checks whether the quality metric itself catches the error.

| Injected fault | Expected detection |
| --- | --- |
| Exchange the incoming and outgoing temperature in one row | Two wrong-column cells |
| Change feet to inches, change °F to °C or remove a unit | Three wrong-unit cells with the original row still aligned |
| Delete one row and duplicate another | One missing row, three missing cells, one duplicate row and three excess cells |
| Exchange a temperature between two depth rows | Two wrong-row cells |
| Reverse row order with the same values | Changed row order |
| Fill a known empty revision cell | One unexpected cell |
| Move a valid grid outside the annotated region or duplicate it inside | Missing or ambiguous grid respectively |

[Automated tests](../../tests/test_benchmark_track_a_scan_cells.py)

## Reproduction

Download the SHA-pinned originals listed in the gold file. Put them in `ORIGINAL_SCAN_DIR` and use the existing local Docling and OCR artifacts. The first command processes the complete FORGE PDF, OzAlpha-1 page 5 and the lossless Mobil TIFF window. The evaluator also accepts the run manifest from a previously created release if the source and release fingerprints still match.

```sh
export HF_HUB_OFFLINE=1
export DOCLING_ARTIFACTS_PATH="$LOCAL_DOCLING_MODELS"
python scripts/run_track_a_scan_cells.py \
  --pdf-dir "$ORIGINAL_SCAN_DIR" --out "$SCAN_RUNS" \
  --models data/interim/ocr_models --full-pdf forge_mudlog
python scripts/benchmark_track_a_scan_cells.py \
  --pdf-dir "$ORIGINAL_SCAN_DIR" --runs "$SCAN_RUNS/runs.json" \
  --out "$SCAN_SCORES"
python -m unittest discover -s tests -p test_benchmark_track_a_scan_cells.py
```

Use `--split development` or `--split holdout` to evaluate one partition without loading the other inputs. The optional `--require-exact` returns status 1 if any selected grid fails and still writes the cell-by-cell report. It fails against the E52 baseline. The development cases can guide implementation and the fixed Mobil measurements can track regression. Reserve a separate source for a fresh holdout after design changes informed by these results.
