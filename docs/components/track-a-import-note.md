# Track A import note

This note records how the Track A code in this branch was produced and what is not established. It adds no new behaviour.

## Origin

- The code was developed and measured in a separate working copy of this repository, against datasets that are not in this repository.
- The sets named "holdout", "fresh" and "unseen" in `docs/experiments` E35-E61 and in `configs/benchmarks` were used during development (profile sweeps, rule design, repeated re-scoring). Read them as development and regression sets.
- Generalization to unseen documents is NOT EVALUATED. No result here is an independent or held-out measurement.
- The source branch commits benchmark references with phrases or rows from third-party PDFs separately. This integration excludes those references pending a check of the source licences.

## Changes that affect shared behaviour

- `configs/corpus/k1.json` changed its defaults on 24 November: eleven repair and recovery switches, seven table rules and `table_join` were turned on. On 25 November each group was measured on the demo package and most were turned off again (Track A log A-D07, [E62](../experiments/E62-track-a-option-measurements.md)): grid recovery, section context and `table_join` as shipped stay on. The 24 November profile is kept as `configs/corpus/candidates/k1_standard_24nov.json`.
- `schemas/k1_table.schema.json` gained optional fields and a conditional rule, and `k1_validate.py` gained two checks. `SCHEMA_VERSION` was not raised.
- Track A publishes the QA retrieval view (`retrieval_chunks.jsonl` with its manifest). The GraphRAG reader changes from the source branch are outside this integration.
- `configs/corpus/daily_reports.json` sets `running_line_min_pages` to 3.

## Licence

- PyMuPDF is AGPL-3.0 or a commercial Artifex licence. The default K1 profile now imports it at runtime (about 18 modules under `src/graph_builder/corpus`), while `pyproject.toml` still lists it only in the optional `qa` extra and some wording in `docs/components/dependencies.md` still describes it as optional. The owner must resolve this before anything is distributed.

## Open items

- Track B and Track C run on the package `demo-v2`, built with its own profile (`configs/corpus/candidates/demo_corpus.json`); they have not tested the extended table schema or the retrieval view.
- The hand-edited lines in `README.md` and `docs/PROJECT_DESIGN.md` are limited to Track A components.
