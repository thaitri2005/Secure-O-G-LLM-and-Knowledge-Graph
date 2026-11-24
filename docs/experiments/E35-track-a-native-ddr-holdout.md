# E35 · Track A native PDF ablation on Utah FORGE daily reports

## Dataset and scoring

The inputs are **12 original one-page daily drilling PDFs** from Utah FORGE well 16A(78)-32, printed in the WellEz template between 21 October 2020 and 3 January 2021. They were downloaded from the public `djimrastephane/ddr-rag-book` mirror at commit `4c94867c3cf1fa0c779e2fb2bdbe2204cf6711f2`. The selection takes 12 evenly spaced dates from the 66 drilling reports outside the mirror's `sample_ddrs` directory. Source filenames, SHA-256 digests, page counts and reference phrases were fixed before running Track A. [Frozen manifest](../../configs/benchmarks/forge_ddr_holdout.json)

These files provide a file-level holdout for the experiment. Track A has seen a separate drilling summary for the same well. All 12 reports use one template, one well and a usable text layer. This experiment does not measure cross-well generalization, scanned pages or OCR accuracy.

- **Word and numeric occurrence scores** compare per-page K1 outputs with the original PDF text layer extracted by PyMuPDF. Recall divides matched occurrences by reference occurrences. Precision divides matches by output occurrences and penalizes duplicates. Corrupted associations can pass occurrence checks.
- **Critical header phrases** are 49 nonblank field-and-value strings from the PDF text layer, covering report date and number, well identity, measured depth, footage and drilling hours where printed. The match requires a contiguous normalized phrase on its page. Markdown table pipe characters count as spaces. This score checks visible label and value adjacency and does not validate the whole table grid.
- **K1 coverage and QA** are recorded per document. Artifact hashes and QA reasons can be inspected alongside content metrics.

## Native execution and timing

A cold seed run invokes Track A's production PDF converter on each original file with Docling Heron and TableFormer fast, then processes the output. The five required model files match the SHA-256 values recorded in [model provenance](../components/model-provenance.md). They were retrieved from the project-published Docling Serve CPU image's model layer (`sha256:24728d962da1f52fb27d18e703707f5811893ba0b4c4538186b8652dafa15451`). The host uses local inference and the benchmark sets Hugging Face offline mode.

The 53-profile sweep holds converter settings fixed. It reuses the native segments produced by the seed and invokes real Track A processing, K1 export and QA from a fresh corpus for each profile. The worker verifies matching PDF hashes, matching conversion settings and a completed seed before copying the segments. A separate cold run can measure the full path by omitting `--native-seed`. Cached timings include loading and staging native segments. Both timing modes exclude harness startup and scoring. Peak RSS measures the isolated worker. The CPU estimate uses a hypothetical USD 0.04 per vCPU-hour. No inference API was used.

## Results

All 52 valid profiles publish K1 for 12/12 reports. The literal 24-option profile fails configuration validation. Each profile in the cached sweep was measured once on Linux x86-64 with an AMD EPYC 9V74 host, a four-CPU cgroup quota and one benchmark worker.

| Profile | Word recall | Numeric recall | Numeric precision | Header phrases | Wall s, 12 pages | CPU s | Peak RSS MiB | Estimated USD/1,000 pages |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Zero options | 89.4% | 94.2% | 93.2% | 14/49 | 6.57 | 6.50 | 391 | 0.00602 |
| Preserve list markers only | 89.4% | 94.2% | 93.2% | 14/49 | 5.73 | 5.65 | 392 | 0.00523 |
| Minimum pages for running-line removal only | 97.3% | 99.6% | 93.4% | 49/49 | 5.71 | 5.65 | 392 | 0.00523 |
| Generic forms only | 96.1% | 99.1% | 83.7% | 49/49 | 6.59 | 6.54 | 392 | 0.00605 |
| First six options | 97.3% | 99.6% | 93.9% | 49/49 | 6.58 | 6.51 | 392 | 0.00603 |
| Cumulative 22 options | 98.0% | 99.7% | 80.7% | 49/49 | 11.57 | 11.50 | 393 | 0.01065 |
| 21 options without generic forms | 97.3% | 99.6% | 93.9% | 49/49 | 10.67 | 10.60 | 393 | 0.00981 |

The clearest one-option gain on this cohort is `running_line_min_pages=3`. It preserves margin lines in single-page reports and recovers 137 numeric occurrences and 35 critical header phrases. `preserve_list_markers` has no measured score effect on these files. The first six options reach the same word and number recall and header coverage as the 21-option profile. Adding generic forms across the other options gains one matching numeric occurrence while producing 438 more excess occurrences of known values. These scores measure text retention and duplicate output. They do not establish correct table-cell assignment or prove that a change transfers to another well or a different template.

### Cold baseline

One independent run read the 12 original PDFs and completed corpus processing, K1 export and QA in **89.06 wall seconds**, **229.94 CPU seconds** and **1,333 MiB peak RSS**. The corpus phase took 87.48 wall seconds, K1 took 1.37 and QA took 0.21. The illustrative CPU-equivalent cost was **USD 0.213 per 1,000 input pages**. K1 chunk, table and form hashes, quality metrics and QA signal counts matched the cached baseline on all 12 files. The cache sweep's timings measure the option-dependent work from native segments. This cold baseline includes layout and table-model inference.

## Reproduction

```bash
git clone https://github.com/djimrastephane/ddr-rag-book.git /tmp/forge-ddr-source
git -C /tmp/forge-ddr-source checkout 4c94867c3cf1fa0c779e2fb2bdbe2204cf6711f2

.venv/bin/python scripts/prepare_forge_ddr_holdout.py \
  --dataset-checkout /tmp/forge-ddr-source \
  --pdf-dir data/raw/forge-ddr-holdout \
  --hf-cache data/interim/forge-ddr-models/hub

export HF_HUB_CACHE="$PWD/data/interim/forge-ddr-models/hub"
export HF_HUB_OFFLINE=1 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4

.venv/bin/python scripts/benchmark_track_a_ablation.py \
  --native-manifest configs/benchmarks/forge_ddr_holdout.json \
  --native-pdf-dir data/raw/forge-ddr-holdout \
  --native-seed data/interim/forge-ddr-native-seed \
  --out data/interim/forge-ddr-native-ablation \
  --usd-per-vcpu-hour 0.04
```

The setup uses the benchmark environment's bundled small RapidOCR files for the pinned OCR configuration. The seeded ablation writes `summary.csv`, `performance.csv` and `results.json` under its output directory. The preparer verifies the model layer and stages the allowlisted files without extracting or executing the container image.

For the independent cold baseline, omit `--native-seed`, add `--only-variant zero` and set `--out data/interim/forge-ddr-native-cold`.
