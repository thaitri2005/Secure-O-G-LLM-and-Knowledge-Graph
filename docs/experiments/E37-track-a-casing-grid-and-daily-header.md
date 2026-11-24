# E37 — Rebuilt casing grids and daily report headers

The casing rule uses printed titles, header labels, PDF vector rulings and word geometry. It preserves column units and empty cells. For a compound native table, it splits a prefix when every removed cell can be attributed to the recovered casing region and remaining cells can be retained. Twelve compound table prefixes met that condition across the two benchmark bundles. Other overlapping content stayed available with review quality. The daily header reader adds cost and depth pairs supported by the printed labels and glyph positions.

The first stage tested a fresh native conversion of FORGE 78B-32 pages 5 and 8 and New Crown 1 pages 1, 10 and 15. Both TableFormer modes scored 0/13 on the pinned casing probes. The timing comparison uses one CPU run per mode, including conversion startup. Fast took 61.8 s and accurate took 55.3 s.

| K1 comparison | Source phrases | Original casing probes | Additional New Crown casing probes |
| --- | ---: | ---: | ---: |
| Matched E36 profile before recovery | 41/45 | 0/13 | 1/7 |
| Matched E36 profile with casing and header recovery | 45/45 | 13/13 | 7/7 |
| Shipped default before recovery | 34/45 | 0/13 | — |
| Shipped default with casing and header recovery | 38/45 | 13/13 | 7/7 |

The matched profile enables generic forms. The shipped profile retains its existing generic-forms setting and still misses seven RIMBase continuation-page phrases, including weather fields and one well ID. The four previously missing Tri-Star phrases pass in both updated profiles. The WellEz regression retained 49/49 phrases with its E36 settings. All scored releases passed structural validation. The matched 35-page export went from 4.4 s to 5.7 s with reused native conversion output, and structural QA, source fidelity, cross-representation QA and retrieval export took about 1.0 s.

The additional casing probes were read from source pages outside the original five-page comparison. They use the same Tri-Star template and well.

| Page | Row anchor | Printed column | Value |
| ---: | --- | --- | --- |
| 3 | `16"` | Wt (lb/ft) | 75ppf |
| 3 | `16"` | Set at (mGL) | 10.5 |
| 12 | `9-5/8"` | N. Joints | 10 |
| 12 | `9-5/8"` | Length (m) | 120 |
| 12 | `7"` | Set at (mGL) | 536 |
| 19 | `7"` | Length (m) | 539 |
| 19 | `7"` | N. Joints | 43 |

Six pages from two additional report formats tested whether a last-casing summary field or narrative would create a false casing table. Both checks preserved identical `chunks.jsonl`, `tables.jsonl`, `forms.jsonl`, `pages.jsonl` and `parents.jsonl` hashes with the rules on and off. This establishes behavior on those negative controls. Positive field accuracy on another operator's casing-table template remains unmeasured.

| Negative control | Original pages | Source SHA-256 |
| --- | --- | --- |
| Myrtle Basin 1 | 1, 10, 35 | `bd48110b9c8ac42452976e14b33a2e50ff44fe917b241479d27595977e788494` |
| Palm Valley 13 | 1, 20, 50 | `0bd08d13e390a78651d9d58c9a3952178ff44e5466785ec3534138f84eb42801` |

The controls use complete unrescaled pages copied from the two public source PDFs. [Myrtle Basin](https://github.com/mhnajafi7/pdf-report-table-extractor/blob/fb1a0b863cb31f8768bdebdc809c23ff5482a8cf/Docs/PR20140005_Daily_Drilling_Report.pdf) · [Palm Valley](https://github.com/mhnajafi7/pdf-report-table-extractor/blob/fb1a0b863cb31f8768bdebdc809c23ff5482a8cf/Docs/PR2019W019_Appendix_F_Daily_Drilling_Reports.pdf)

Run the matched-profile gate from the repository root using the local Docling model cache.

```sh
python scripts/benchmark_form_overlap.py \
  --manifest configs/benchmarks/track_a_cross_template_holdout.json \
  --pdf-dir data/raw/track-a-cross-template --fetch --casing --daily-header \
  --require-all-probes --out data/interim/casing-header-repro
```
