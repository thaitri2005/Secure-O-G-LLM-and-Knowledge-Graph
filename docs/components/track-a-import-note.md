# Track A import note

This note records how the Track A code in this branch was produced and what is not established. It adds no new behaviour.

## Origin

- The code was developed and measured in a separate working copy of this repository, against datasets that are not in this repository.
- The sets named "holdout", "fresh" and "unseen" in `docs/experiments` E35-E61 and in `configs/benchmarks` were used during development (profile sweeps, rule design, repeated re-scoring). Read them as development and regression sets.
- Generalization to unseen documents is NOT EVALUATED. No result here is an independent or held-out measurement.
- The source branch commits benchmark references with phrases or rows from third-party PDFs separately. This integration excludes those references pending a check of the source licences.

## Changes that affect shared behaviour

- `configs/corpus/k1.json` changed its defaults: eleven repair and recovery switches, seven table rules and `table_join` are now on. The default K1 output differs from earlier releases.
- `schemas/k1_table.schema.json` gained optional fields and a conditional rule, and `k1_validate.py` gained two checks. `SCHEMA_VERSION` was not raised.
- Track A publishes the QA retrieval view (`retrieval_chunks.jsonl` with its manifest). The GraphRAG reader changes from the source branch are outside this integration.
- `configs/corpus/daily_reports.json` sets `running_line_min_pages` to 3.

## Licence

- PyMuPDF is AGPL-3.0 or a commercial Artifex licence. The default K1 profile now imports it at runtime (about 18 modules under `src/graph_builder/corpus`), while `pyproject.toml` still lists it only in the optional `qa` extra and some wording in `docs/components/dependencies.md` still describes it as optional. The owner must resolve this before anything is distributed.

## Open items

- Track B and Track C have not tested the new defaults, the extended table schema or the retrieval view.
- The hand-edited lines in `README.md` and `docs/PROJECT_DESIGN.md` are limited to Track A components.
