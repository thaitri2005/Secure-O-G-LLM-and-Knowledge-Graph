# E38 — Track A benchmark on 229 drilling-report pages

The corpus contains 79 original PDFs and 229 pages across five report families. The 176 pages reserved for the new-page score comprise 63 other WellEz PDFs, 57 Myrtle Basin pages and 56 Palm Valley pages. The latter two reports were processed as complete 60-page and 59-page PDFs so that document-level filtering saw their original page boundaries. Earlier experiments had examined three pages of each. The remaining 47 pages are the complete E35/E36 regression groups.

| Source family | PDFs | Pages | Literal source phrases | Exact table cells |
| --- | ---: | ---: | ---: | ---: |
| WellEz FORGE 16A | 75 | 75 | 334 | — |
| RIMBase 7.5 FORGE 78B-32 | 1 | 15 | 79 | 5 |
| Tri-Star New Crown 1 | 1 | 20 | 104 | 26 |
| Armour Energy Myrtle Basin 1 | 1 | 60 | 283 | 8 |
| Central Petroleum Palm Valley 13 | 1 | 59 | 471 | 8 |
| Total | 79 | 229 | 1,271 | 47 |

The manifest pins the PDFs, the page split and the checks. Literal phrase checks include report numbers, well identity, date, cost, depth, and selected weather items from the source. The table samples cover 31 casing cells and 16 operating-log cells. A table cell passes when its row anchor, printed column and value identify a unique match in K1. Word and number recall are per-page text-layer token counts. These measure presence across the page and can give credit when a field belongs to the wrong row or label. [Pinned manifest](../../configs/benchmarks/track_a_scale_holdout.json)

All profiles use one Docling Fast CPU conversion with the three-page minimum for removing running lines. The historical K1 profile disables casing and daily-header recovery. The current default adds both. The generic profile also enables generic forms. All three run structural, source-fidelity, cross-representation and form/text overlap QA. Literal phrase and token scores use the resulting retrieval view, and table scores use K1.

## Results

| K1 profile | Source phrases | Exact cells | New-page phrases | Numeric occurrences matched | K1 export | QA and retrieval export |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Before casing/header recovery | 839/1,271 | 15/47 | 635/999 | 47,055/48,072 | 22.7 s | 8.0 s |
| Current default | 856/1,271 | 43/47 | 635/999 | 47,056/48,072 | 23.9 s | 8.3 s |
| Current default with generic forms | 985/1,271 | 43/47 | 727/999 | 47,400/48,072 | 38.6 s | 10.0 s |

All three releases passed structural validation for 79 PDFs and 229 text-layer pages. The new default gained 17 source phrases and 28 casing cells while retaining every previously matched probe. The casing probes rose from 3/31 to 31/31. The 16 time-log probes on the new pages reached 12/16 with each profile. Form/text deduplication retained every pinned phrase found in each canonical K1 release.

| Source family | Before → default → generic phrase matches | Before → default → generic cell matches |
| --- | ---: | ---: |
| WellEz FORGE 16A | 334 → 334 → 334 / 334 | — |
| RIMBase 7.5 FORGE 78B-32 | 45 → 45 → 79 / 79 | 0 → 5 → 5 / 5 |
| Tri-Star New Crown 1 | 85 → 102 → 102 / 104 | 3 → 26 → 26 / 26 |
| Armour Energy Myrtle Basin 1 | 158 → 158 → 198 / 283 | 8 → 8 → 8 / 8 |
| Central Petroleum Palm Valley 13 | 217 → 217 → 272 / 471 | 4 → 4 → 4 / 8 |

Generic forms removed 1,344 duplicate fields in the retrieval view. Surplus occurrences of numbers already found in the source still increased from 10,937 to 14,563 compared with the default. This is a page-level overlap count rather than a count of duplicate extracted facts.

Myrtle Basin page 2 retains the well name and permit value in the default text. The chunk lists both labels before both values, so the source pairing misses the probe. In Palm Valley, the two sampled time rows on page 13 are present in the grid, but K1 labels the printed header as a body row. Page 30 has no separate time-log table in K1. Cross-representation QA also flags one Palm Valley table chunk whose text drops `GAS:` and `TRIP` from the corresponding grid row in all three profiles.

## Conversion time

Native conversion ran on 182 pages and reused validated native output for 47 regression pages. Conversion and recovery took about 19 min 38 s on a four-vCPU machine and consumed approximately 1.11 CPU-hours in the benchmark processes. The pipeline used local Docling weights.

The initial three-worker batch stalled after two workers reached their 20-document recycling limit. Two single-worker retry runs started processing the remaining short PDFs while the Palm Valley conversion continued. The final catalog adopted 23 recovered outputs and held a completed native conversion for every input PDF. Each parallel submission in the rerun command now contains up to 20 documents, within a worker lifetime.

## Reproduction

Run from the repo root with the local Docling model cache and QA dependencies available.

```sh
python scripts/benchmark_track_a_scale.py \
  --pdf-dir data/raw/track-a-scale --fetch \
  --out data/interim/track-a-scale-repro --workers 3
```

`--reuse-corpus` accepts a processed corpus with the same configuration and source hashes. `--processing-stats` can attach a separately timed conversion run. The JSON results include per-document misses, before/after comparisons, export and QA timing, and the paths to the QA ledgers.
