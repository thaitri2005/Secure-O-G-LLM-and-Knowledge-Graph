# Note for Khai: what to build next, in detail

**From:** Tri (Track B), 24 November 2026 · **Still holds:** the [earlier note](../B-graphrag/note-for-track-A-daily-reports.md) on daily reports · **Plan tasks:** D1 to D5 in the [plan](../../DEVELOPMENT_PLAN.md#7-what-to-do-now)

This is your work list for the data side, in the order that unblocks the most. Each task says what to build, the steps, and how to know it is done. You know the ingestion code far better than I do, so where I name a file it is a pointer, not an instruction.

## Update, later on 24 November: Tasks 1, 4 and 5 have a first version

With your clearance three of the tasks below were built the same day (Track B log B-C55). **They are yours to check and correct**; nothing was switched on by default and no K1 field was added.

| Task | State | What is left for you |
|---|---|---|
| 1. The demo release (D1) | Built: `python scripts/build_k1_demo_release.py` gives `ak3-demo-v1`, 1,051 chunks, with appendix 23, the legacy map and a well on end-of-well chunks. The five checks pass; the legacy map covers 15 of the 17 gold chunks | Check it against how you would have built it. It uses today's `k1.json` (Operations Summary rule on), not the candidate's configuration: 31 event descriptions differ in wording from E28's (B-F64). The well comes from a new optional setting, `document_context` |
| 2. Which options go on (D2) | Not done | Yours, on this release |
| 3. Two more end-of-well reports (D3) | Not done | Yours. It also unblocks rebuilding the facts on the new IDs (B-F63) |
| 4. Merged-cell text (D4) | The mode `span_once_keyed` already fixes it; a test now shows it. On the demo release it clears both high character-ratio warnings and changes no ID | Decide whether to switch it on (with D2) |
| 5. A dated log (D5) | A draft: [log.md](log.md), written from the repository's history | Correct it; it guesses at nothing, but it is not your account |
| The two tests without PyMuPDF | They skip with a reason | — |
| A title per report; a region on passages | Not done | As below |

## Why it matters now

An application now sits on top of your output ([frontend/](../../../frontend/README.md)). It shows report text to users exactly as K1 gives it, lists sources by report and page, and draws a timeline from the operations tables. What K1 contains is now what a person sees.

## Task 1 (D1): one K1 release for the demo

**Why first:** Hung's loader and my engine both wait for it.

**Build:** a single K1 version 1 release with these files, and tell Hung and me where it is.

| Include | Detail | Check |
|---|---|---|
| AK-3's end-of-well report | As in your candidate | Your validator passes |
| The four daily-report attachments (appendices 27 to 30) | As in your candidate | 979 of 979 daily chunks carry a report date and a well |
| **Appendix 23, the non-productive-time report** | File `gdr882-ak3-appx-23-5-nonproductivetimerpt-160927`. Its table has the columns the activities need: the non-productive code, the date, from, to, hours, depth, the activity code, the description | `python -m graphrag.events build --k1 --name check` gives **161 events**, and no event's chunk ID contains `#` |
| **`legacy_chunk_ids.json` inside the release** | The map from old chunk IDs to new ones (`export --legacy-chunks`). The candidate you gave me had it; the package Hung loaded did not | Hung's `platform/load_k1.py` reports a legacy map, and it covers the 17 gold chunks the prototype's questions cite (15 of 17 today) |
| **A well on end-of-well chunks** | `context.well` on every chunk of the end-of-well report, as daily chunks have | No end-of-well chunk without a well. Hung's vectors stop guessing it from the text |

**Steps**

1. Add appendix 23 to the corpus the release is built from, and build the release.
2. Run your validator and the QA sidecar on it.
3. Run my compatibility check: `python scripts/check_k1_graphrag_compat.py`. It should report no gaps.
4. Run the event check above.
5. Share it: on Hung's shared store once it exists, not in chat.

**Done when:** all five checks in the table pass on one release.

## Task 2 (D2): decide which of your new options go on

**Build:** a short record, per option, of what it changes on the demo release.

| Option (17 November) | Measure on the demo release | Decide |
|---|---|---|
| Table joining across pages | Tables joined, and whether any join is wrong; the 81 Operations Summary tables must stay whole | On or off |
| Section context | Share of passages whose section heading is right, on a sample | On or off |
| Form recognition, label-value repair | Pairs right on your annotated forms, with the option on and off | On or off |
| Page orientation | Rotated pages found and read; the 13 rotated pages you counted earlier are the test | On or off |
| Table Markdown modes | Whether merged-cell text still repeats (Task 4) | Which mode |

For each: the number with the option off, the number with it on, and the decision. If an option changes K1's fields, it needs a new K1 version, announced to Hung and me first.

**Done when:** each option is on or off by default with a number behind it, in your log (Task 5).

## Task 3 (D3): two more end-of-well reports

**Build:** add 56-32 and 68-32 to the demo release.

1. Process both reports with the settings Task 2 decided.
2. Check the casing tables by eye against the PDFs: they are what my table rules read (13 of 16 right on unseen reports).
3. `context.well` on their chunks, as in Task 1.

**Done when:** "Which of AK-3, 56-32 and 68-32 was drilled deepest?" can be asked from the stores.

## Task 4 (D4): duplicated merged-cell text

**Build:** the fix for table Markdown repeating the text of a merged cell, which is your progress report's first priority and also causes false QA alarms.

**Done when:** the three high character-ratio pages you found no longer raise the alarm, and a table with a merged header shows its text once.

## Task 5 (D5): a dated log

**Build:** `docs/tracks/A-ingestion/log.md`, like [Track B's](../B-graphrag/log.md) and [Track C's](../C-storage/log.md): a "current state" table on top, then dated entries (`A-F` findings, `A-D` decisions, `A-C` design choices).

Start it with the 17 November work, which is not written down anywhere as a dated entry: what each option does, what you measured, what is still open.

**Done when:** someone who was not there can tell what changed on 17 November and why.

## Three smaller things the application showed

| What | Why | Proposed |
|---|---|---|
| **A title per report** | The application names a source "AK-3 end-of-well report" by guessing from the file ID | A `title` on the K1 file record; I then drop the guess |
| **Where a passage is on its page** | To highlight the cited passage on a page image | A region (page coordinates) on passage chunks, as tables have. Tell me if K1 already carries it |
| **Two tests fail without PyMuPDF** | `tests/test_corpus_table_join.py` fails to import, and `test_broken_pdf_is_recorded_and_other_documents_survive` in `tests/test_qa_multipage_scan.py` errors, on a machine without it. My laptop's full run shows 2 errors for this | Skip with a reason when it is missing, as your other tests do |

## What changed on my side that touches you

- `graphrag` reads K1 version 1 as before. Nothing in your contract changed.
- The application replaces the PDF's private bullet characters (such as U+F0B7) with a bullet for display, and changes nothing else. If you would rather clean such characters in K1, tell me and I will remove that.
- The design of the whole is in [specification §4.6](../../PROJECT_DESIGN.md#46-second-build-one-connected-application); the stint's summary is in the [stint report](../../reports/stints/STINT_REPORT_2026-11-27.md).

## What I need from you

1. The demo release (Task 1), and a rough date for it.
2. Whether passages can carry a region.
3. Anything in this note that does not fit how the pipeline really works.
