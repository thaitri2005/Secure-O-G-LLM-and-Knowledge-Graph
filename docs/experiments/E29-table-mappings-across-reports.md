# E29: Table mappings across reports from other authors

| | |
|---|---|
| **Date** | 5 November 2026 |
| **Question** | E25 tried the mappings on one unseen report from the same project. Do they work on reports from other operators and authors, in other layouts and units? |
| **Requirement** | B-D20, B-F39, risk R-01 |
| **Input** | Named run `e29_all` (ignored by git), registry [`gdr_e29_unseen.json`](../../configs/sources/gdr_e29_unseen.json): 7 reports. `data/processed/` is unchanged |
| **Code** | `graphrag/tables.py`, `graphrag/table_eval.py`, `graphrag/validate.py`, `graphrag/retrieval.py` (well names), K2 version 1.2 |
| **Gold data** | [`e29_table_gold.json`](../../graphrag/gold/e29_table_gold.json), frozen before any fix: casing strings read by hand from the PDF pages, and survey rows computed from the PDFs' text layer. Independent of the parsed tables. Not expert-reviewed |
| **Models** | None |
| **Outputs** | `graphrag/results/E29_*.json`; scores in `E29_score_as_is.json` and `E29_score_second.json` |
| **Status** | Done |

## Reports and how they were used

Fixes came only from the first report. The others were not used to write rules.

| Report | Role | Author and layout |
|---|---|---|
| TNT-GT-01 (Netherlands) | **Dev**: fixes come from this | Well Engineering Partners; metres |
| TNT-GT-02 | Held out | Same consultant and template as dev, so an easy test |
| HON-GT-01-S2 | Held out | Same consultant, different table |
| HEK-GT-02 | Held out | Same consultant, 2014 |
| Utah FORGE 58-32 | Held out | GRG, the layout the mappings came from |
| Raft River RRGE-3 (Idaho, 1976) | Held out | **Different author and era**, partly scanned |
| Utah FORGE 16A(78)-32 summary | Held out, no gold | Narrative, 3 tables; 0 facts, not judged |
| Utah FORGE 78-32 | Regression | E25's report |

## Results

**Casing strings**, right size and bottom depth, in the report's unit:

| Report | As written | After fixes | After fixes and validation |
|---|---:|---:|---:|
| TNT-GT-01 (dev) | 0/3 | 3/3 | 3/3 |
| TNT-GT-02 | 0/3 | 3/3 | 3/3 |
| HON-GT-01-S2 | 0/3 | 3/3 (1 wrong fact) | 2/3 |
| HEK-GT-02 | 0/4 | 4/4 | 4/4 |
| 58-32 | 4/4 | 4/4 | 4/4 |
| Raft River RRGE-3 | 0/2 | 0/2 | 0/2 |
| **Held out in total** | **4/16** | **14/16** (1 wrong fact) | **13/16 (0 wrong facts)** |
| 78-32 (regression) | 3/3 | 3/3 | 3/3 |

Validated is what reaches the answer model. On HON-GT-01-S2, a liner hanger depth (`5 = 2354 m`) contradicts the true 2606, and the validator drops both: a safe failure that loses one right fact.

**Survey rows**, right measured depth and inclination:

| Report | Rows | As written | After fixes (wrong) | After validation (wrong) |
|---|---:|---:|---:|---:|
| TNT-GT-01 (dev) | 210 | 0 | 33 (1) | 25 (0) |
| TNT-GT-02 (held out) | 198 | 0 | 99 (7) | 81 (7) |
| 78-32 (regression) | 20 | 20 | 20 (0) | 19 (0) |

**Cost per page:** no LLM calls. Parsing is about 1 to 2 seconds per page.

**On the original three reports,** 4 facts of 154 went away and none was added. All 4 are junk, such as an inclination of -14.2° or a depth equal to its angle. Fact recall on AK-3 is unchanged at 28 of 41.

## What was wrong, and the fixes

All are general rules, from the dev report.

| Problem | Effect | Fix |
|---|---|---|
| The well-name pattern could not read `TNT-GT-01` | No facts at all from such reports | Names with several parts. Well names on the original reports are unchanged |
| Casing named in an `Item` column, with `⅜` fractions | Table not recognized | `casing_items` mapping; sizes in one form |
| Mixed strings continue on rows with no item | Wrong depth | Keep the string's deepest bottom |
| **Depths in metres** | Would have been labelled feet | Facts carry `unit`, and metre surveys use `depth_m` |
| Depth column named `MD` | Survey missed | K2 accepts `md` |
| Parser merges survey rows (`114.20 125.50` over `0.20 0.10`) | Rows lost or misread | Split only when cells pair up; otherwise skip |
| Cement table has the same layout as a casing table | `13-3/8 = 135 m` (top of cement) | Skip tables with a TOC column |
| Shifted columns | `1.46°` among 32° readings | Drop readings far from their neighbours |
| **The strict validator looked for `13-3/8` in text saying `13 ⅜"`** | **It discarded right facts** | It accepts each way of writing a size |

The last one matters most. The raw score looked good while almost nothing reached the model, which is why the table now reports both.

## What was learned

1. **The caveat was justified.** As written, the mappings found nothing outside GRG's layout, though they also stated nothing false.
2. **Casing now generalizes across these layouts:** 13/16 with no wrong fact. Most of the gain is on one consultant's reports, so this shows three layouts more, not all layouts.
3. **Surveys are not reliable yet.** Half the rows at best, and 7 of 88 validated rows on TNT-GT-02 are wrong (8%). The cause is the parser merging dense tables. Treat metric survey facts as unsafe until K1 version 1, and do not use them for answers from these reports without checking.
4. **Scanned reports are out of reach.** Raft River's text comes out column by column, so there are no rows to map. Only Track A's OCR or table work can change that.

## Limits

- **The held-out test is not fully clean.** The first round of fixes was scored on all reports at once, and the second round came after seeing those scores. Its rules came from the dev report's errors, and the held-out errors (HON's hanger depth, TNT-GT-02's 2706 against 2707) were left unfixed. One fix, to the shifted-column filter, came from the regression reports and can only keep more rows.
- Only one held-out report has a truly different author, and it fails. **We still have no evidence on a different author's modern digital report,** which would be the real test.
- Only casing depth and survey rows are scored. Casing weight and grade, rig and contractor were not scored here, and rig-time and temperature tables did not appear in the gold. The mappings still miss key-value forms such as 78-32's `Total Depth (ft): 3,280 ft`.
- The gold was read by the author of the fixes, from 7 reports.
- Two reports fail the ingestion's own page-coverage check (TNT-GT-02 p. 29, Raft River p. 7), with output still produced.
- The Dutch reports' licence terms were not checked (`public-unverified` in the registry). The PDFs are not in the repository; use them for development only.
- Widening the strict check could change E26's and E27's strict fact-sheet runs if rerun. Their recorded results stand, and the fact sheet is optional (B-D24).
