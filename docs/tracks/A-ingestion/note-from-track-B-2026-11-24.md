# Note for Khai: what the second build needs from data

**From:** Tri (Track B), 24 November 2026 · **Replaces nothing:** the [earlier note](../B-graphrag/note-for-track-A-daily-reports.md) on daily reports still holds · **Plan tasks:** D1 to D5 in the [plan](../../DEVELOPMENT_PLAN.md#7-what-to-do-now)

Thank you for taking the data role. This is what the application now being built needs from K1, in order. The first item blocks two other people; the rest do not.

## Do first

**D1. One K1 release for the demo.** Target: this week.

| It must contain | Why | How to check |
|---|---|---|
| AK-3's end-of-well report and the four daily-report attachments, as today | The demo's questions are about AK-3 | Your validator |
| **Appendix 23, the non-productive-time report** (`gdr882-ak3-appx-23-5-nonproductivetimerpt-160927`) | The daily activities take their non-productive codes from it. Today I read it from the old corpus export, so 28 of the 161 activities still carry old chunk IDs ([E31](../../experiments/E31-event-graph-on-k1.md)) | `python -m graphrag.events build --k1 --name check` gives 161 events, and none of their chunk IDs contains `#` |
| **`legacy_chunk_ids.json` inside the release** | Our gold answers and Hung's loader map old IDs through it. The candidate you gave me had it; the one Hung loaded did not | Hung's `platform/load_k1.py` reports a legacy map |
| **The well on end-of-well chunks** (`context.well`), as daily chunks have | Hung's vectors need a well to filter on; today his loader guesses it from the text | Every chunk of the end-of-well report has a well |

When it is ready, tell Hung and me where it is. Once his shared store exists it goes there, not in chat.

## Then

| Task | What | Done when |
|---|---|---|
| **D2** | Decide which of your 17 November options are on by default (table joining, section context, form recognition, label repair, orientation), each by a measurement on this release | Each option is on or off with a number behind it |
| **D3** | Add the 56-32 and 68-32 end-of-well reports to the release | Questions that compare wells can run from the stores |
| **D4** | Fix the duplicated merged-cell text in table Markdown | Your progress report's first priority is closed |
| **D5** | A dated log in this folder, like Tracks B and C keep. The 17 November work is not written down anywhere as a dated entry | Findings and decisions since 9 November are in it |

## Three smaller things the application showed

- **A title for each report.** The application names a source "AK-3 end-of-well report" by guessing from the file ID. A `title` on the file record would replace the guess.
- **Where a passage is on its page.** To highlight the cited passage on a page image we need its region. Tables carry regions; do passages?
- **Two of your tests fail where PyMuPDF is not installed** (`tests/test_corpus_table_join.py`, and `test_broken_pdf_is_recorded_and_other_documents_survive` in `tests/test_qa_multipage_scan.py`). On my laptop the full suite shows 2 errors for this reason. A skip with a reason, as your other tests do, would keep the suite clean on machines without it.

## What changed on my side that touches you

- `graphrag` reads K1 version 1 as before; nothing in your contract changed.
- The application shows report text exactly as K1 gives it. Private-use bullet characters from the PDF (U+F0B7) are shown as bullets; everything else is untouched. Anything odd in the text will now be seen by users, so tell me if you would rather clean a class of character in K1.

Ask me anything that is unclear. The design is in [specification §4.6](../../PROJECT_DESIGN.md#46-second-build-one-connected-application).
