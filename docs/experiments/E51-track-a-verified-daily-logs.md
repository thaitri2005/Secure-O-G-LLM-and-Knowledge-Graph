# E51 · Verified multi-page daily logs

The default Track A profile reconstructs a ruled daily log when both PDF readers agree on the four printed columns, every horizontal band and the content in the resulting cells. The supported schema includes a date, a report number, a midnight depth with an explicit unit and the narrative summary. The reader preserves the printed unit and the full description. It only replaces a native table that occupies the same physical region. [Reader](../../src/graph_builder/corpus/daily_log.py)

Adjacent parts join when they share the report heading, edition, page-counter sequence, ruled column coordinates and compatible report context. The last report on the preceding page and the first complete report on the continuation must also have consecutive report numbers and increasing dates. When the first row on the continuation contains only a description and is followed by the next report, the description is appended to the preceding row. K1 records separate cell fragments and the two physical pages, and QA checks each fragment in its original rectangle. This split case is covered by a generated test with another complete row after the fragment. The generic table join stays opt-in. [Split-row test](../../tests/test_corpus_daily_log.py)

## Original report benchmarks

Both cases use selected windows of the original CTSCo well completion publication. Each window includes the original neighbouring pages before and after the table. West Moonie-1 was the development case. West Moonie-2 is a different well and edition from the same operator and layout family. Its references came from independently clipped regions and date anchors on the original pages. The benchmark checks rows in source order, keeps the printed depth unit and verifies the source rectangles. [Source manifest](../../configs/benchmarks/track_a_verified_daily_logs.json)

| Measure | West Moonie-1 | West Moonie-2 |
| --- | ---: | ---: |
| Exact date, report number and depth | 25/35 → **35/35** | 15/24 → **24/24** |
| Exact full rows including description | 10/35 → **35/35** | 6/24 → **24/24** |
| Valid joins across source page boundaries | 0/4 → **4/4** | 0/3 → **3/3** |
| Independently confirmed cells after the change | **144** | **100** |

The previous generic join also joined 3/4 West Moonie-1 boundaries, with the same 10/35 exact full rows. The new reader separates reports 14 and 15 on original page 27 before joining. Both neighbouring-page controls retained the same retrieval text. A generated negative test keeps aligned tables separate when the printed well identity or report context changes. [Prior comparison](E50-track-a-panel-alignment-and-natural-layouts.md)

## Retrieval on the 79-PDF regression corpus

A native rectangle can extend beyond the border of an independently verified panel. QA clears such a rendered cell only when the independent read of the native rectangle matches its complete text and uniquely matches the complete source cells in the same physical region. When the box includes other text or more than one verified panel offers a match, the native cell stays in the retrieval view. K1 source records remain intact. [Projection rule](../../src/graph_builder/corpus/qa/ruled_overlap.py)

On the same K1 release, the expanded bounds cleared **310 additional rendered positions** and reduced surplus numeric occurrences from **11,271 to 11,195**. Word occurrence matches went from 94,060 to 94,046 and number occurrence matches from 47,628 to 47,627. Every previously matched distinct source word and number type stayed retrievable on its page. Both views matched 1,271/1,271 phrase probes, 47/47 exact-cell probes and 624/624 hourly rows. Page-scoped BM25 stayed at 9/10 source rows in its top five. Four Volve PDFs and 40 pages produced an identical retrieval view.

## Cold timings for the two slow reports

Both PDFs were converted again in fresh corpora with local model weights, then exported through K1 and full QA. Each conversion used one worker. New Crown ran first and included model startup. These single-run differences include machine and startup variation.

| PDF | E50 total | E51 total | E51 Docling | E51 K1 | E51 QA |
| --- | ---: | ---: | ---: | ---: | ---: |
| New Crown, 20 pages | 267.7 s | 287.6 s | 276.2 s | 7.4 s | 3.9 s |
| Palm Valley, 59 pages | 727.7 s | 666.2 s | 609.1 s | 39.4 s | 17.7 s |

Docling still accounts for about 91–96% of total cold time on these two files. E51 changes the K1 table reader and QA projection. Both cold releases passed validation.

## Reproduction

Download the SHA-pinned original listed in the source manifest and place it in `$ORIGINAL_PDF_DIR`. Use the same local Docling model weights for both conditions.

```sh
python scripts/benchmark_track_a_verified_daily_logs.py \
  --pdf-dir "$ORIGINAL_PDF_DIR" --out "$LOG_RESULTS" --models data/interim/ocr_models

python -m graph_builder.corpus qa "$CORPUS" --release "$RELEASE" --out "$QA_DEFAULT" \
  --fidelity --crossrep --cell-evidence
python -m graph_builder.corpus qa "$CORPUS" --release "$RELEASE" --out "$QA_STRICT" \
  --fidelity --crossrep --cell-evidence --no-ruled-native-margin
python scripts/benchmark_ruled_overlap.py --release "$RELEASE" --pdf-dir data/raw/track-a-scale \
  --before "$QA_STRICT/retrieval_chunks.jsonl" --after "$QA_DEFAULT/retrieval_chunks.jsonl" \
  --out "$RETRIEVAL_RESULTS"
```
