# Track A progress report: document ingestion and tables (K1 version 1 candidate)

| | |
|---|---|
| **Status date** | 9 November 2026 |
| **Branch** | `track-a-k1-package`, merged into `main` on 9 November 2026 after review by Track B (614 tests pass) |
| **Owner** | Track A (Khai) |
| **Contract status** | The chunk and table id format of K1 v1 is **adopted** (specification D-54, 9 November 2026), and Track B's `graphrag` reads it (Track B log B-C28). The six `k1_*` schemas are still for Track C to review |
| **Requirement** | Track A in the [development plan](../DEVELOPMENT_PLAN.md); chunk package K1 version 1 (specification §5.10, §5.11) |
| **Scope of this report** | What is implemented, what was measured on which data, what is open. Every number states its dataset; "seen" data was used to build the method, so it is a regression check and not evidence of generalization |

## 1. Scope and pipeline

Track A turns drilling-report PDFs into a K1 chunk package (files, pages, parents, chunks, tables, forms) with stable ids that point back to file and page.

```
PDF -> corpus pipeline (Docling layout/tables, OCR for scanned pages)        -> corpus output (JSONL + text)
    -> K1 stage: ids (§5.11), parents/chunks, forms, report date + well,
                 specialised correction of known table formats (A-107)       -> K1 release (SHA256SUMS, manifest)
    -> K1 validator (schemas, references, offsets, checksums, page rebuild)  -> release is published or refused
    -> QA sidecar (read-only): ledger, source fidelity, cross-representation,
                 annotations, margin signals                                  -> qa-ledger.json (not part of K1)
```

Design rules: the K1 v1 contract is unchanged by the QA work; QA output is a sidecar linked to a release by stable ids and the release checksum; specialised rules run only when the format is recognised and fall back to the general parser (Docling) with a recorded reason otherwise; output is deterministic (two exports give identical `SHA256SUMS`).

## 2. What is implemented

| Component | Where | What it does |
|---|---|---|
| Corpus pipeline fixes | `corpus/process.py`, `corpus/chunking.py`, `ingestion/filters.py` | Cold and cached conversion read the same document; optional `keep_line_patterns` keeps data lines that repeat on many pages (for example the weather strip) |
| K1 v1 package (**proposed** contract) | `corpus/k1_build.py`, `k1_export.py`, `k1_validate.py`, `k1_config.py`, `schemas/k1_*.schema.json`, `configs/corpus/k1.json` | Six record types, text files, manifest, checksums, validator, `k1` command |
| Forms and report context | `corpus/forms.py`, `text_layer.py`, `report_context.py`, `form_scoring.py` | Key-value pairing for the RIMBase daily-report header from the PDF text layer; report date and well on every daily-report chunk |
| Old-to-new chunk ids | `corpus/legacy_ids.py` | Maps old chunk ids to K1 ids for one document |
| Operations Summary reconstruction (A-107) | `corpus/ops_tables.py`, `table_recognition.py`, `configs/corpus/k1.json` | Rebuilds the Operations Summary table of the RIMBase daily report from the PDF text layer; four outcome states (validated, recognised but failed, unsupported format, parsing failure); falls back to Docling with a reason |
| Parser benchmark (A-501) | `scripts/benchmark_tables.py`, `configs/benchmark_tables.json` | Compares table extraction methods on shared datasets |
| QA package (A-401, A-402, A-403, A-401a, A-412, A-414) | `corpus/qa/`, `configs/qa/`, `python -m graph_builder.corpus qa` | Quality ledger, source fidelity vs the PDF text layer, cross-representation checks, "N records not printed" annotation check, Operations margin signal, explained page exclusions |
| Measurement scripts | `scripts/evaluate_ops_tables.py`, `regress_ops_tables.py`, `qa_*_eval.py`, `qa_multipage_scan.py`, `qa_annotation_scan.py`, `check_k1_graphrag_compat.py` | Evaluation, regression and scanning; most need the source PDFs |
| Tests | `tests/` | 614 tests run from a clean checkout (section 6) |

## 3. Experiments and results

All "ground truth" below is the PDF text layer, or gold annotations made by one annotator with AI assistance. That makes these checks of consistency with the PDF text, not of agreement with an independent human reading.

**3.1 K1 v1 candidate** ([E30](E30-k1-version-1-candidate.md)). Five documents of one well (the AK-3 end-of-well report and four daily-report attachments): 174 pages. The validator reports 0 errors and the page rebuild matches on 174 of 174 pages; two exports give identical checksums. Form pairing on 5 annotated RIMBase forms: 141/141 pairs (development) and 93/93 (held out, same template). Report date and well on 979/979 daily-report chunks. These are consistency measurements on one report family.

**3.2 Operations Summary tables (A-107)**. 81 tables, 481 rows, 92 non-productive marks in three daily-report attachments (27 report days of one well; the three attachments repeat the same days).

| Metric (denominator) | Docling only | Rule, round 1 independent held-out (9 days) | Rule, round 2 on all days (**seen data**) |
|---|---|---|---|
| Tables found | 77/81 | 27/27 | 81/81 |
| Header correct | 51/81 | 26/27 | 81/81 |
| Rows matched | 475/481 | 205/205 | 481/481 |
| Marks in the right column | 76/92 | 33/41 | 92/92 |

The round 1 held-out figures are the only independent result; its two failures were tables whose title line carried an annotation, which the round 2 recognition now accepts. Round 2 numbers are a regression on data already seen. Further checks: 807/807 deliberate corruptions were not accepted as validated (they fell back with a reason); uniform scaling of the page between 0.5 and 2.0 left the output unchanged; with position noise three times the design level, 16 of 405 cases were validated but different (known risk, partly flagged by the margin signal). Of 29 pages of the same template in 47 other PDFs, 2 were read correctly (both already seen), 14 stopped at a code format the rule does not accept, and 13 were rotated pages; no false positive was observed on 642 pages without the table. Same-family independent generalization is **not evaluated**.

**3.3 Parser comparison (A-501)**. Methods: Docling fast and accurate, pdfplumber, Camelot, PyMuPDF `find_tables`, and the A-107 rule. Datasets are reported separately.

| Dataset | Result |
|---|---|
| 10 gold tables | Tables detected: Docling fast 10, Docling accurate 10, Camelot stream 9, PyMuPDF 7, pdfplumber lines 4, Camelot lattice 4 |
| 81 Operations tables (seen) | Detected: Docling fast 77, Camelot stream 74 (wrong column structure), pdfplumber lines 32, Camelot lattice 20, PyMuPDF 0, A-107 rule 81 (built on this data) |
| Pages without tables | The negative labels turned out unreliable: 13 of 20 flagged pages did contain a table, so no false-positive rate is claimed |

Median seconds per page: Docling fast 2.6 on pages converted fresh, Docling accurate 6.1, pdfplumber 0.1 to 0.3, Camelot 0.1 to 0.6, PyMuPDF 1.6. Docling accurate was run on a sample only. Reading: Docling is the default table parser; the A-107 rule is a specialised correction for one table format; the line-based libraries are useful as cross-checks, not as detectors.

**3.4 Quality assurance sidecar (A-401, A-402, A-403, A-412, A-414)**. The checks report warnings and what they cannot see; none of them marks content as verified.
- Source fidelity (compares words and numbers with the PDF text layer, text pages only), two releases of the tuned family: 163 text pages, 3 warnings. Deliberate corruptions: a fabricated sentence containing a number was detected in 158/158 cases, one changed digit in 141/157, small deletions in about 24/150, swapped or reordered text in **0/155**.
- Cross-representation (tables vs table chunks, forms vs form chunks, row ranges): 0 warnings on the real releases; a corruption in one place was detected in 60/60, the same corruption made consistently in both places in **0/60**.
- Annotation scan over 94 PDFs (1,252 pages): 23 hits (13 unique) of the form "N record(s) not printed" or "(N not shown)", in Mud Reports (16), Operations Summary (6) and surveys. K1 v1 has no field for this annotation; the QA ledger records the table scope as partially printed.
- Page 3 of the AK-3 end-of-well report (empty in K1) is a table of contents removed on purpose; the three high character-ratio pages were false alarms caused by Markdown table syntax and duplicated merged-cell text. The pipeline was not changed; QA now reports an explained exclusion.
- On four PDFs not used to tune the thresholds (296 pages, EasyOCR used for the hybrid pages because the other OCR model files were not available offline): 136 pages carried warnings and a viewed sample of 20 flagged pages gave a precision of 8/20 (40%). The thresholds are therefore **noisy outside the family they were tuned on** and have not been recalibrated.

**3.5 Multi-page table scan (A-108a, measurement only)**. In the five RIMBase documents: 195 tables, 69 pairs of consecutive pages that both hold tables, 0 continuation candidates. This says nothing about other report families; the multi-page requirement (FR-25) is still open.

## 4. Task status

| Task | State |
|---|---|
| K1 v1 package, forms, report context (E30) | Implemented; consistency verified on one family; id format adopted (D-54), schemas awaiting Track C's review |
| A-107 Operations Summary reconstruction | Implemented; conditionally accepted by the owner for the template and data above |
| A-501 parser comparison | Done within the limits above |
| A-401, A-402, A-403, A-401a, A-412, A-414 QA checks | Implemented; warning-only; thresholds not calibrated across families |
| A-108a multi-page measurement | Done (measurement only) |
| Multi-page tables (FR-25) | **Not implemented** |
| Section context (labels at the top of a page) | **Not implemented**; known to be wrong on some pages |
| Forms outside the RIMBase template; form areas that are tables | **Not implemented** |
| Duplicated merged-cell text in table Markdown | **Known defect**, not fixed |
| Scanned (OCR-only) pages | **Not evaluated**: the available documents had no pure scan pages |
| Document VLM comparison (plan work 2) | **Not run** |
| Calibration of the QA thresholds on other families | Pending |

## 5. Known limitations

- **Generalization.** Every method was built and tuned on one well and one report family (RIMBase). Behaviour on other formats is documented only by the small unused-document checks above. No claim is made for PDFs in general.
- **Source fidelity.** The checks compare K1 with the PDF text layer. They cannot detect swapped or reordered content, a wrong label-value pairing, an error inside the text layer itself, OCR errors without a reference, or a table whose structure is wrong while its words are right. "Consistent with the text layer" is not "correct".
- **Source completeness.** A PDF may state that records were not printed. K1 v1 does not carry this; the QA ledger does, as a partial-source marker. A table without that marker is not proven complete.
- **Ground truth.** The gold tables are 10; annotation is by one person with AI assistance; the unused-document precision estimate rests on 20 pages.
- **Contract and integration.** The id format is adopted (D-54) and `graphrag` reads it (B-C28); Track C's `k1_chunk.v0` schema stays for version 0. Still open: Track C's review of the six schemas, and a quality or verification status, source completeness and annotations in the contract. *(Updated by Track B on 9 November after the merge.)*
- **Scale.** Timings are single-machine measurements (for example about 5 seconds per page for the end-to-end conversion of four unused documents on CPU). No scalability claim is made.
- **Reviews.** The reviews so far were done with the same development tooling; no independent human code review has taken place yet.

## 6. How to run

Environment: the packages in `requirements.lock.txt`. The benchmark and some evaluation scripts additionally use PyMuPDF, pdfplumber and Camelot, which are not in the lock file. The source PDFs (public GDR reports, see [Data sources](../DATA_SOURCES.md)) are not in the repository; `data/raw/` is ignored.

```text
# tests (from a clean checkout, without data/raw): 614 tests, OK, skipped 12 to 16
python -m unittest discover -s tests          # set PYTHONPATH=src when the package is not installed

# build a K1 package (see docs/components/corpus-ingestion.md)
python -m graph_builder.corpus init <corpus> ; add ; process ; k1 <corpus> --name <name>

# quality sidecar for a release (read-only)
python -m graph_builder.corpus qa <corpus> --release <release> --fidelity --crossrep --ops-margin --annotations --out <dir>
```

Tests that need local data skip themselves with a stated reason: the source PDFs (3 groups), the corpus work folder or a real K1 release, optional packages (`PyMuPDF`, `requirements-graphrag.lock.txt`). The K1 package is not in the repository by design: it was shared with the team as a zip on 9 November, and it can be regenerated from the PDFs.

## 7. Next priorities

1. Fix the duplicated merged-cell text in table Markdown (it also causes false QA alarms).
2. Calibrate the QA checks on more than one family and re-measure on data not used for the calibration.
3. Multi-page tables (FR-25): measure on the end-of-well reports and other families first, then implement against written acceptance criteria.
4. Section context, forms outside the template, form areas that are tables.
5. Agree the remaining K1 contract points with Track B and Track C (a quality or verification status, source completeness, annotations); the id format is settled (D-54).
6. The K1 package was shared as a zip on 9 November (not committed). Confirm the chunk count (1,042 in the message, 1,040 in E30) and that its ids are the D-54 format.
