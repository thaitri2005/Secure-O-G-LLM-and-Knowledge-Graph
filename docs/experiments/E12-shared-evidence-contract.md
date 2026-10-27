# E12: Shared evidence, claim and entity contract on real outputs

| | |
|---|---|
| **Date** | 27 October 2026 |
| **Question** | Can one evidence contract cite both a corpus chunk and a dataset row, pinned to the release they came from, for every record the existing pipelines produce? |
| **Requirement** | FR-02, FR-15, FR-16; design §3.3 gap 2, §7.1; plan backlog item 7 |
| **Input** | The E8 AK-3 appendix export (`data/corpora/ak3_appendices/exports/v1`, 1,778 chunks) and the E6 BSEE bundle (`data/processed/local/datasets/bsee_wells`, 58,040 records); both local and ignored, written before releases existed (read as `flat`) |
| **Code** | [`graph_builder/contracts.py`](../../src/graph_builder/contracts.py); [`schemas/evidence.schema.json`](../../schemas/evidence.schema.json), [`claim.schema.json`](../../schemas/claim.schema.json), [`entity.schema.json`](../../schemas/entity.schema.json); tests in `tests/test_application_contracts.py` |
| **Gold data** | None; the check is schema validity and ID uniqueness |
| **Status** | Passed |

## The contract

| Record | Identity | Pins |
|---|---|---|
| Evidence | `ev:` + digest of source, release and locator | Original file SHA256; release name and digest of its `SHA256SUMS`; for a chunk: chunk ID and SHA256, page, regions, quote and its offsets; for a row: record ID, file, ZIP member, row, cited fields |
| Claim revision | `cl:` logical claim (profile, subject type and key, property, qualifier, context); `cr:` revision (adds value, evidence, origin, kind) | Profile version; origin (`model_extraction` with model and prompt, `dataset_mapping`, or `manual`) |
| Entity | `ent:` + digest of the first identifier, or of type, scope and name key | Profile; scoped identifiers; language-tagged names |

Consequences, each covered by a unit test:

- A re-export gives new evidence IDs, so an accepted claim never silently points at changed text.
- A quote not found verbatim in its chunk is refused.
- Correcting a value keeps the claim ID but makes a new revision.
- Linking the subject to a registry entity does not make a new revision.
- Two names with one API number are one entity.

## Results

| Input | Records | Valid evidence | Distinct evidence IDs |
|---|---:|---:|---:|
| AK-3 appendix export (corpus chunks) | 1,778 | 1,778 | 1,778 |
| BSEE bundle (dataset records, one field cited each) | 58,040 | 58,040 | 58,040 |

Both passes took 275 s in total on the laptop, almost all of it per-record JSON Schema validation. That is acceptable for an audit; a bulk path should validate a sample or use a compiled validator.

## Not covered

- Persisting these records in PostgreSQL and moving the prototype onto them (it still uses its own claim JSON).
- Claim revisions built from real extraction or dataset mappings at scale; only unit fixtures so far.
- Entity resolution itself (matching mentions to registry entities); only the entity record and its ID rule.
