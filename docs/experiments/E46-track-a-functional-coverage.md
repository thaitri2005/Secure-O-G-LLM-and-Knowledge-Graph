# E46 — Report context, continuations and ruled report panels

## Report context

K1 keeps the existing verified report context and fills unresolved text pages from visible well labels and report dates. The fallback uses the printed header on each page. For slash dates with two possible orders, it uses unambiguous dates in the same document and well to establish the convention. When the order remains ambiguous, the page keeps its context exception. Stacked report pages stay under the existing boundary handler. [Context implementation](../../src/graph_builder/corpus/report_context.py)

The existing drilling corpus has 79 PDFs and 229 text pages. The E45 package marked 214 pages without context and exposed both context fields on 114 of its 2,053 chunks. The E46 candidate fills both fields on all 229 pages and all 2,168 emitted chunks. Published dates matched the independent references on 75 Forge 16A pages and 59 Palm Valley pages.

## Continuations and run diagnostics

A table whose continuation lacks a header can join when both pages resolve to the same report, geometry aligns, and a measured-depth or other recognized sequence continues. If Docling rendered the first numeric row of the continuation as a header, K1 keeps it in the logical grid with the original page reference. The QA retrieval view supplies the first page's column labels and renders that numeric row as body data. The retrieval row records the header's source page in `table_header_page`. A cold Docling run on a two-page generated continuation preserved all 16 data rows and recovered the reported first row on page two. This behavior remains opt-in through `table_join`. [Join decisions](../../src/graph_builder/corpus/table_join.py) · [Retrieval headers](../../src/graph_builder/corpus/qa/table_headers.py)

K1 preserves rows exceeding the configured character budget and marks the corresponding chunks `review`. QA issues `TABLE_CHUNK_OVER_BUDGET` with the chunk, table, row range and configured limit. The latest corpus run had 40 such chunks on 11 pages and all 40 were marked for review. QA can also count tokens with a supplied local `tokenizer.json`. A QA run records the tokenizer checksum and token limit. This measures the table chunk as passed to the tokenizer. The caller accounts for prompt overhead in the selected budget.

K1 records abstentions by page, rule and reason in the checksummed manifest. QA emitted `TABLE_RECONSTRUCTION_ABSTAINED` on 109 pages in the scale run. These diagnostics cover candidates seen by configured rules. Unsupported layouts can fall back to native output, and unfamiliar layouts can still require review. [QA checks](../../src/graph_builder/corpus/qa/builtin_checks.py)

## Specialized panels

The candidate adds survey, bit, BHA, inventory and end-of-well key–value layouts with printed titles, verified ruling geometry and typed data rows. PDFium constructs each grid. PyMuPDF independently confirms the visible text inside each emitted cell rectangle. A panel with disagreeing evidence stays in native extraction and receives an abstention reason. An actual New Crown page produced a disagreement in two BHA cells and exercised this fallback. The end-of-well key–value path was verified from source PDF to K1 and QA on a generated report. Real end-of-well and rotated scan coverage still need independent evaluation. [Panel readers](../../src/graph_builder/corpus/ruled_panels.py)

The scale corpus produced 115 new panels, comprising 76 survey, 25 bit, nine BHA and five inventory tables. An independent replay matched the text in all 3,529 emitted nonempty cell rectangles. The joiner kept all 98 candidates in this natural corpus separate. The candidate retains the native tables alongside verified panels, so the same number may appear in more than one retrieval chunk. The E45 regression still measures 32/32 pinned mud rows, 47/47 pinned cells and 624/624 hourly pairs. The independent hourly geometry check still covers 1,248 cells. [E45 benchmark](E45-track-a-compound-table-quality.md)

## Reproduction

Reuse the scale corpus from E38 and pass the candidate to `k1`. For token checks, optionally append `--table-tokenizer /path/to/tokenizer.json --table-max-tokens 512` using the downstream model's file and budget. The optional ruled-panel reader uses the same PyMuPDF dependency as QA.

```sh
python -m graph_builder.corpus k1 "$CORPUS" --name table-coverage-e46 \
  --k1-config configs/corpus/candidates/k1_full_table_candidate.json
python -m graph_builder.corpus qa "$CORPUS" --release "$RELEASE" --out "$QA_DIR" \
  --fidelity --crossrep --form-overlap --table-overlap --cell-evidence
```

The development checkout supported `$QA_DIR/retrieval_chunks.jsonl` through `GRAPHRAG_K1_RETRIEVAL_CHUNKS` and the original `chunks.jsonl` through `GRAPHRAG_K1_CHUNKS` for canonical lookups.
