# E62: Which reading options are on by default (Track A, D2 and D4)

| | |
|---|---|
| **Date** | 25 November 2026 |
| **Question** | For each reading option added on 17 November and each group of settings main turned on on 24 November: what does it change on the demo release, and is it on by default? Which table Markdown mode is the default? |
| **Requirement** | Plan tasks D2 and D4; Track B's note of 24 November, Tasks 2 and 4 |
| **Input** | The eight demo PDFs of `demo-v2` (end-of-well reports of AK-3, 56-32 and 68-32; appendices 23 and 27 to 30; 302 pages), converted once with `configs/corpus/candidates/demo_corpus.json` (fingerprint `e99d077b7d5ffcb5`); the Docling segments of AK-3's report and appendices 27 to 30 were reused from earlier runs with that fingerprint, appendix 23, 56-32 and 68-32 were converted again. Variants that only change chunking (table Markdown, label-value repair, orientation `flag`) reuse the same segments |
| **Code** | main `efffa0d`, interpreter of the Docling environment, PyMuPDF 1.28.2; `python -m graph_builder.corpus k1 ... --legacy-chunks`, then `qa --fidelity --crossrep` (ledger schema 1, same code on both sides) |
| **Gold data** | None independent. Page images and the PDF text layer read by one reader; the 96 geometry-checked form pairs of A-435 (development pages) |
| **Outputs** | Not committed (`data/interim/`, ignored). The numbers are in the Track A log, A-F23 to A-F29 |
| **Status** | Done on development data. Generalization beyond these eight files is NOT EVALUATED |

## Rules, written before the numbers

An option or group is on by default only if all of these hold on the demo release:

1. the K1 validator passes;
2. the id of no unchanged item changes (or a mapping is documented and the owner informed);
3. in the page-image sample no changed item is REGRESSED and most are IMPROVED;
4. the 81 Operations Summary tables stay whole;
5. the time of the export is at most 2x, or the benefit clearly outweighs it (numbers stated);
6. it changes no K1 field; otherwise it stays off and the entry says "needs a new K1 version, to announce to Track B and C".

An option that does not fire on the demo release has no evidence on this data and is off by default, unless the repository already holds evidence for it (cited, development data). Decision values: ON, OFF, ON-ONLY-FOR-CONFIG, NOT DECIDED.

## Results

| Option or group | Off | On | Decision |
|---|---|---|---|
| Table Markdown `span_once_keyed` (D4) | 16 `CHAR_RATIO_HIGH`, 283,071 table characters | 14, 278,524; 0 ids changed; 2 of 14 changed tables lose a group label | OFF (`docling`) until the guard is fixed |
| Table joining | 0 joins in 104 candidate pairs; 0 of 10 true continuations joined | candidate profile: 3 joins, all correct | ON as shipped; ON-ONLY-FOR-CONFIG `k1_table_join_candidate.json` |
| Section context | wrong heading 14 of 38 passages, right 17 of 38 | wrong 2, right 17 | ON |
| Form blocks | 61 of 75 pairs, 7 of 20 blanks | 75 of 75, 20 of 20; 12 form ids change page | OFF |
| Form recognition | 61 of 75 | 61 of 75 (no change) | OFF |
| Page orientation | 40 sideways pages, 97.1% of PDF words found | `flag` same; `normalize` 94.6%, 6 tables lost, 50 ids renamed; `verify` 97.2%, 21 ids renamed | OFF |
| Label-value repair | 65 `review` chunks | 228; 262 chunks rewritten; no pair score | OFF |
| Document type from the PDF title | daily chunks with date and well 1,051 of 1,051 | 969 of 1,024 | OFF |
| Numeric repair | no change | no change | OFF |
| Grid recovery | 10 tables differ, all PDF words present | | ON |
| Scan grids and fields | no change | no change | OFF |
| Hourly, casing, mud, daily-log, well-completion rules | 82 chunk ids renamed, new table-part key | | OFF |
| Daily header and report fields | 52 of 75 pairs | 61 of 75, 1 truncated | OFF |

## What the numbers do not show

- One reader judged every label; one blind re-check of 5 headings found 3 consistent and 2 undecidable by text position.
- The demo release is the development data of every option here. No independent document was used.
- The 40 sideways pages are all in one report (68-32); the other families have none.
- Numeric repair and scan grids do not fire on these files. Their off decision follows the rule for options that do not fire, and their K1 field note, not a measured harm.
- The group "daily header and report fields" is borderline: 9 more pairs right against 1 truncated value.
- Timing is one run per configuration on one machine.

## Reproduction

`python scripts/build_k1_demo_release.py` builds the corpus; the toggles are copies of `configs/corpus/k1.json` (or of `configs/corpus/candidates/k1_standard_24nov.json` for the groups) with one setting changed, exported with `python -m graph_builder.corpus k1 <corpus> --name <n> --k1-config <copy> --legacy-chunks data/processed/gdr_chunks_full.jsonl`.
