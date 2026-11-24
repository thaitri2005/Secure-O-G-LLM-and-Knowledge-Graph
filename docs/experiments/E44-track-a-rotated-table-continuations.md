# E44 — Rotated text pages and table continuations

The joiner compares native table geometry and PDFium words in the frame used for conversion. It leaves tables separate when their resolved report dates or wells disagree. A repeated header must match the printed PDF text and the header grids in both parts. The logical grid keeps repeated body rows. The removed header is recorded in `parts[].header`.

`qa --cell-evidence` uses each part's native table reference and exact grid rows to link the released row numbers to the source. The sidecar projects a normalized cell rectangle to the displayed original PDF. `pages.jsonl` records both angles in `rotation_attempts`. A matching native rectangle proves the text at that location. The ruled-grid check remains the stronger source of row and column evidence for reconstructed tables. [Join implementation](../../src/graph_builder/corpus/table_join.py) · [Cell evidence](../../src/graph_builder/corpus/qa/cell_evidence.py)

## Verification

The two generated test PDFs span six text pages. One has a true continuation across an upright page and a page with `/Rotate 90`, followed by two separate tables with `/Rotate 180` and `/Rotate 270`. The other has a true continuation whose second page draws the content sideways and uses `/Rotate 0`.

| Configuration | Expected continuations joined | Expected separate pairs kept separate | Native cell text matching the original PDF region |
| --- | ---: | ---: | ---: |
| Joining enabled, orientation disabled | 0/2 | 2/2 | 71 of 138 output cells |
| Joining and orientation enabled | 2/2 | 2/2 | 132 of 132 output cells |

Each joined table has 17 logical rows. Its repeated header is the only discarded grid row. An independent check used PyMuPDF to read the original visible text inside all 132 reported rectangles. The cold CPU process spent about 13 seconds on the four-page PDF and 11 seconds on the two-page PDF when processed in separate invocations. These runs used local models with no per-call API cost. Timings include model startup and were measured on one machine.

On the existing 79-document, 229-page drilling corpus, the candidate considered 83 page pairs. It left 81 separate and marked two uncertain. Five pairs had a known report-context change. K1 kept all 639 tables and the 1,989 chunks. Only the join metadata for the four tables in uncertain pairs changed. The retrieval view was byte-identical to E43. It retained 1,266/1,271 pinned phrases, 47/47 pinned cells and 624/624 hourly pairs. The separate clock check again verified 1,248/1,248 cell rectangles. [Scale benchmark](E38-track-a-scale-benchmark.md) · [Cell-evidence benchmark](E43-track-a-cell-evidence.md)

On 40 existing Volve control pages, the cell evidence and retrieval outputs were also byte-identical to E43. The positive continuation cases are generated. Field accuracy for natural multi-page continuations and rotated scans remains unmeasured. The new join candidate and orientation normalization stay opt-in.

## Reproduction

Run the geometry and join fixtures in the standard unit suite. To opt in for a new corpus, set `analysis.page_orientation` to `{"mode": "normalize"}` in its ingestion config before `init` and `process`. Export with the candidate and run cell QA on the returned release path.

```sh
python -m unittest discover -s tests -p 'test_page_orientation.py'
python -m unittest discover -s tests -p 'test_corpus_table_join.py'
python -m unittest discover -s tests -p 'test_qa_cell_evidence.py'

python -m graph_builder.corpus k1 "$CORPUS" --name table-continuations \
  --k1-config configs/corpus/candidates/k1_table_join_candidate.json
python -m graph_builder.corpus qa "$CORPUS" --release "$RELEASE" --out "$QA_DIR" \
  --orientation --cell-evidence
```
