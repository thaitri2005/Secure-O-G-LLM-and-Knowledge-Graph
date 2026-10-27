# E13: Entity registry from BSEE and conservative resolution

| | |
|---|---|
| **Date** | 27 October 2026 |
| **Question** | Built from the BSEE bundle by configuration alone, does the registry give every wellbore and well one entity, and how often can a well be identified from a name and lease without risking a wrong match? |
| **Requirement** | FR-05, FR-16; design §5.4, §5.7, §5.9 ("one object, one node"); plan backlog item 7 |
| **Input** | E6 BSEE bundle (`data/processed/local/datasets/bsee_wells`, snapshot of 18 Oct 2026; local, ignored) |
| **Code** | [`graph_builder/registry.py`](../../src/graph_builder/registry.py), [`configs/registry/bsee_wells.registry.json`](../../configs/registry/bsee_wells.registry.json), [`tests/test_registry.py`](../../tests/test_registry.py); entity and evidence records from [E12](E12-shared-evidence-contract.md) |
| **Gold data** | Self-consistency: each wellbore's own names, resolved back, must return that wellbore and no other |
| **Outputs** | Ignored: `data/processed/local/registry/bsee_wells/releases/<id>/` (`entities.jsonl`, `evidence.jsonl`, `summary.json`) |
| **Status** | Passed |

## Build

| Entities | Count |
|---|---:|
| Wellbore (identifier `bsee_api12`) | 57,453 |
| Well (identifier `bsee_api10`) | 39,518 |
| Former identifiers (renumbered wellbores) | 172 |
| Lease-scoped names | 114,822 |

The counts match [E3](E3-reproduction-run-2026-10-25.md) exactly. Each entity cites evidence for its identifier: the dataset row, pinned to the dataset release. The build takes 57 s and is published as a release behind an atomic pointer ([E11](E11-publication-and-import-fixes.md)).

## Resolution rules

1. An exact identifier, in any spelling ("API 01-203-20165-00"), resolves; so does a former identifier.
2. A name resolves only with a scope (here the surface lease) and only if exactly one entity has that name there. Otherwise the result is "ambiguous".
3. A name without a scope never resolves, even if only one entity carries it: the result is "needs_review" with the candidates.
4. Similarity never resolves anything.

## Results

Every wellbore's lease-scoped names, resolved back:

| Mention | Resolved | Ambiguous | No such name | Resolved to the wrong wellbore |
|---|---:|---:|---:|---:|
| Name + lease (`001` on `G01234`) | 30,683 (53.4%) | 26,728 | 42 | 0 |
| Name + sidetrack suffix + lease (`001 ST01BP00` on `G01234`) | 56,603 (98.6%) | 808 | 42 | 0 |

- Name and lease alone are not enough: 10,299 name-and-lease pairs are shared by several wellbores, mostly sidetracks of one hole. That confirms design §5.7, where names are not identities.
- With the suffix, the remaining 808 are true duplicates in the source data. They go to review rather than being guessed.
- Identifier lookups resolve for every wellbore and well. Loading the registry takes 1.6 s; all 114,822 lookups take under 10 s.

## Not covered

- Mentions from reports: no report in the current corpus names a BSEE well, so report-to-registry linking is not measured (design §1.3).
- Pronouns and descriptive references; that is in-document reference resolution (FR-22), before the registry.
- Storage in PostgreSQL, merge history and reversal; the registry is a file release for now.
- A labelled ambiguity set (G4); this is self-consistency on the regulator's own data.
