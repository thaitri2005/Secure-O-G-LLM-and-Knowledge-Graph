# E47 — Retrieval projection for corroborated ruled tables

`qa --ruled-table-overlap` adds a retrieval-only projection for rebuilt mud, survey, bit, BHA, inventory and casing panels. It uses the cell evidence from the same validated K1 release. The retained panel must have complete source-backed evidence and an intact table chunk. A projected cell must match the original PDF words in its native rectangle. The source cells in the same rectangle must account for its entire text, including signed and decimal values. Ambiguous geometry and unmatched text stay in the retrieval view. [Implementation](../../src/graph_builder/corpus/qa/ruled_overlap.py)

When a native cell covers several proven rows or columns, retrieval can omit the combined cell and keep the separate values from the ruled panel. The QA ledger records the native cell, the masked positions and the exact source table and cells. On Palm Valley page 1, the combined native value `8.45 9.05` is omitted and the two density values remain in separate source columns. Adjacent native content and the original K1 record remain available. The earlier hourly projection can run alongside this check. [Hourly projection](E42-track-a-table-overlap.md)

## Results

Both profiles use E46 release `20261123T031007Z-6134fb3ff462`, 79 PDFs and 229 text pages. Both enable form and hourly overlap. The candidate adds ruled overlap. Ten page-scoped BM25 probes check whether the source-backed chunk for a pinned row appears in the first five results. A competing chunk is another result on that page containing all tokens of the pinned row. [Probe rows](../../configs/benchmarks/track_a_ruled_retrieval.json) · [Benchmark script](../../scripts/benchmark_ruled_overlap.py)

| Measure | E46 view | E47 view |
| --- | ---: | ---: |
| Surplus numeric occurrences | 15,023 | 11,701 |
| Competing chunks across the ten top-five searches | 10 | 4 |
| Searches with source-backed evidence in the top five | 9/10 | 9/10 |
| Pinned literal phrases in the retrieval view | 1,266/1,271 | 1,266/1,271 |
| Pinned structured cells in K1 | 47/47 | 47/47 |
| Ordered hourly rows in K1 | 624/624 | 624/624 |

The candidate changed 228 chunks on 154 pages. It removed 615 duplicate text spans and masked 2,952 rendered cell positions. The latter includes representations of 190 native cells with proved row or column conflicts. The checks found zero lost distinct source word or number types on affected pages. The K1 checksums passed and cell-evidence output was byte-identical. The four Volve control documents and 40 pages produced byte-identical retrieval views. QA and export of the view took about 40 seconds on this machine with the existing conversion cache. Both steps ran locally.

The same mud-gels probe on Palm Valley page 10 missed the top-five source target in both variants. The ranked probes are a focused regression. They measure competing evidence when the page is known. Numeric occurrence coverage decreased from 47,636 to 47,622 because a surviving duplicate can account for a same-number occurrence elsewhere on the page. [Coverage metric](E42-track-a-table-overlap.md)

## Reproduction

```sh
python -m graph_builder.corpus qa "$CORPUS" --release "$RELEASE" --out "$BEFORE" \
  --fidelity --crossrep --form-overlap --table-overlap --cell-evidence
python -m graph_builder.corpus qa "$CORPUS" --release "$RELEASE" --out "$AFTER" \
  --fidelity --crossrep --form-overlap --table-overlap --ruled-table-overlap --cell-evidence
python scripts/benchmark_ruled_overlap.py --release "$RELEASE" --pdf-dir data/raw/track-a-scale \
  --before "$BEFORE/retrieval_chunks.jsonl" --after "$AFTER/retrieval_chunks.jsonl" --out "$AFTER/results.json"
```
