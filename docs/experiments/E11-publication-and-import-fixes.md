# E11: E9 defects fixed and rerun as regression tests

| | |
|---|---|
| **Date** | 27 October 2026 |
| **Question** | Do the publication, dataset-identity, header and generation-check defects reproduced in [E9](E9-repository-review.md) stay fixed, as tested behavior rather than one-off probes? |
| **Requirement** | FR-09, FR-15, G1; design §4.3, D-24; plan backlog item 6 |
| **Input** | Temporary synthetic fixtures (the same shapes as the E9 probes) |
| **Code** | [`graph_builder/publication.py`](../../src/graph_builder/publication.py) (new), `corpus/export.py`, `datasets/importer.py`, `datasets/readers.py`, `prototype/kgproto/extract.py`; tests in `tests/test_publication.py`, `tests/test_datasets.py`, `prototype/test_ontology.py` |
| **Gold data** | Expected behavior per probe (below) |
| **Outputs** | Test results only |
| **Status** | Passed: 136 main tests, 11 prototype tests |

## Probes and results

| E9 probe | Before | Fix | Regression test | After |
|---|---|---|---|---|
| Interrupt a corpus export replacement after the first rename | Published path absent; old data under `.old` | Immutable `releases/<id>/` plus a `CURRENT.json` pointer switched by one `os.replace`; the previous release is kept | `test_interrupted_pointer_switch_keeps_the_current_release` (the pointer replacement is made to fail) | Previous release current and readable |
| Dataset re-import that fails | Could retire the good bundle before validation found the problem | Full bundle validation runs on the staged bundle; publication only if it passes | `test_failed_reimport_keeps_the_current_release`, `test_invalid_staging_is_never_published` | Previous release current; staging removed |
| Two identical generated IDs, no natural `key` | Import succeeded; validation failed afterwards | Record IDs are unique per import independent of `key` (`duplicate_record_id` error) | `test_duplicate_record_ids_fail_without_a_natural_key` | Import fails; nothing published |
| CSV `code,depth,depth` with `A,100,999` | `depth=999`; 100 silently lost | Duplicate header names stop the read; blank header cells get positional names | `test_duplicate_headers_are_refused` | `ValueError` naming the duplicates |
| Prototype date `2016-02-31`; month `13` | Passed; `IndexError` | Calendar parse before evidence checks ([E10](E10-profile-driven-prototype.md)) | `test_impossible_dates_are_rejected_not_raised` | "not a calendar date" |
| Prototype generation with one accepted claim failing to project (static finding) | Counts nonzero, so checks passed | Frozen expected set of (claim, evidence chunk) compared exactly with the projection; digest and problems stored per generation | `test_partial_projection_fails_the_exact_set_check` | "missing b <- doc#c2"; generation not activatable |

`python -m unittest discover -s tests`: 136 tests, OK (150 s; previously 128). `python -m unittest prototype.test_ontology`: 11 tests, OK.

## What changed for users

- Corpus exports: `exports/<name>/CURRENT.json` + `exports/<name>/releases/<UTC time>-<digest>/`. Read with `graph_builder.publication.current_release`. Old flat exports remain readable until the next export of that name.
- Dataset bundles: the same layout under the output directory; `validate --output` checks the current release.
- Prototype generations: `generations.expected_digest` and `generations.problems` columns (added in place with `ALTER TABLE … IF NOT EXISTS`).

## Not covered

- Atomicity on network file systems; the pointer switch was tested on a local NTFS volume.
- A real power loss: the interruption was simulated by making the pointer replacement fail.
- The legacy PDF pipeline's file-copy publication (kept frozen for reproduction).
- Cache-identity gaps (OCR runtime versions, converter reuse) and redirect checks before requests, which E9 also listed; still open.
- A live Neo4j run of the exact-set check; it is unit-tested on the comparison function and will run in the next prototype generation.
