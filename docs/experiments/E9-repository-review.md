# E9: Repository review and local verification

**Current direction:** English-first oil-well delivery on a reusable core (D-26/D-27). This record preserves the experiment/review as run; profile-driven extraction and QA remain integration work. See the [specification](../PROJECT_DESIGN.md#44-core-and-domain-profile-boundary).

| | |
|---|---|
| **Date** | 27 October 2026 |
| **Question** | Which implemented contracts hold locally, and which reliability/evaluation gaps must be addressed before application integration? |
| **Requirement** | FR-01/02/06/07/09/10/11/12/13/15; gates G1, G3, G6–G8 |
| **Input** | Repository baseline `e20395f`, existing Windows environment/caches, temporary synthetic inputs |
| **Code** | Main test suite, `prototype.test_ontology`, corpus publication, dataset readers/importer and prototype ontology |
| **Gold data** | Existing fixtures; synthetic expected behavior for fault/input probes. No new domain annotations |
| **Outputs** | [Repository assessment](../REPOSITORY_REVIEW_2026-10-27.md), documentation corrections and next backlog |
| **Status** | Review completed; identified runtime fixes remain open |

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m unittest prototype.test_ontology
```

128 main tests passed in 17.191 seconds; four prototype ontology tests passed. No skip was reported; the cached PDF regression ran. Docling warned about clamping cached coordinates outside page bounds. No model inference, downloads, live database services or GPU workload were run for the review.

After the oil-well/English scope update, the same suites passed again: 128 main tests in 18.477 seconds and four prototype ontology tests. All 318 local links/heading references in 27 Markdown documents resolved, and `git diff --check` passed. Diagrams 02/04/09 were regenerated from Mermaid and visually checked. The unified report retains eight pages and six figures; rendering verifies all 176 text blocks. Documentation changes do not resolve the runtime defects below.

## Temporary-fixture findings

| Probe | Observed result | Required behavior |
|---|---|---|
| Raise after moving current corpus export to `.old`, before installing staged export | Published path absent; old data retained in `.old` | Immutable validated release and atomic publication pointer |
| CSV `code,depth,depth` with `A,100,999` | Row became `code=A, depth=999`; first depth lost | Reject duplicate/empty normalized headers or require positional mapping |
| Dataset with two identical generated IDs, no natural `key` | `run_import` returned success; subsequent validation reported duplicate ID | Validate staged outputs and identity before installation |
| Prototype date `2016-02-31`, quote `31 February 2016` | Validator returned no error | Calendar validation rejects impossible dates |
| Prototype date month `13` | `IndexError` | Invalid output becomes bounded candidate rejection |

The probes used temporary directories and did not modify accepted data. They were review diagnostics, not newly committed regression tests or fixes.

## Static findings and limits

Generation validation does not compare the expected accepted claim/evidence set with actual projected IDs; nonempty partial projection can pass. Corpus processing fingerprints omit collected OCR runtime versions, and converter reuse keys only on format/mode. URL redirect checks occur after requests have followed redirects. The application authorization, parser isolation, migrations, independent recovery and installed-wheel contracts remain unfinished. These findings were identified in code, not validated by live attack/load testing.

Keep E4 as development-set integration evidence. Freeze an independent document split before the next prompt/model comparison; score full context/evidence and useful coverage, and measure a real reviewer. This review executed the local checks listed above. The unified progress report also covers the project's method-evaluation and graph-construction results; their dataset and run scopes remain attached to those experiments.
