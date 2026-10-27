# E10: Prototype driven by an ontology file

| | |
|---|---|
| **Date** | 27 October 2026 |
| **Question** | Can the prototype take its ontology as an input file (specification D-29, FR-19) without losing extraction quality, and does a different ontology run through the same code? |
| **Requirement** | FR-19 (core), FR-21 (seed), FR-22 (prompt rule only); D-28 to D-30; E9 calendar-date defects |
| **Input** | Same 15 AK-3 chunks, 41 gold facts and 31 questions as [E4](E4-ak3-architecture-prototype.md); `prototype/profiles/oil_wells.json`; `prototype/profiles/synthetic_library.json` |
| **Code** | [`prototype/kgproto/profile.py`](../../prototype/kgproto/profile.py), [`curate.py`](../../prototype/kgproto/curate.py), updated `extract.py`, `api.py`, evaluators; [`test_ontology.py`](../../prototype/test_ontology.py) |
| **Gold data** | E4's development gold, unchanged (single annotator, AI-assisted; in-sample) |
| **Outputs** | `prototype/results/extract_v5.log`, `extraction_run<N>.json`, `qa_v5_*.json` once the run completes |
| **Status** | Code and offline checks done; the model run (prompt `extract-v5`) is in progress |

## What changed

| Before (E4) | After |
|---|---|
| The ontology (14 properties), output schema, validator and gold matcher were Python code in `ontology.py` | They are generated from `profiles/oil_wells.json` (`oil_wells@0.2`) by a generic loader; `KG_PROFILE` selects another file |
| The extraction prompt named AK-3, TG-2 and TG-4, and mixed domain and generic rules | Prompt = profile task and domain rules + rules generated from context fields + core rules; the AK-3 document context is a run input in `extract.py` |
| No rule for "it" / "the well" | Core rule: resolve such references to the named subject, or leave the fact out (FR-22, prompt level only; not separately measured) |
| `2016-02-31` passed validation and month `13` raised `IndexError` (E9) | Both are rejected as "not a calendar date" |
| No duplicate search | `curate.py` groups subject names by the profile's match key and lists look-alike keys for a person (suggestions only) |
| Neo4j label `ReportWell` hardcoded | Label comes from the validated profile; unchanged value for `oil_wells` |

The loader rejects every problem at once: unknown units, qualifiers, context fields or normalizers; missing definitions; non-snake-case names; reserved field names; duplicate JSON keys; files over 256 KB.

## Offline checks (done)

- 10 prototype tests pass (previously 4). They cover:
  - the validator rules;
  - impossible dates;
  - the synthetic profile validating and matching claims with no well vocabulary in its prompt;
  - invalid profiles reporting all their problems;
  - duplicate keys and unknown normalizers being rejected;
  - duplicate search grouping "AK-3", "Akutan Well AK-3" and "ak 3", suggesting AK-3/AK-31 and not TG-2/TG-4.
- Both profile files validate (`python -m prototype.kgproto.profile prototype/profiles/*.json`).
- 128 main tests pass, unaffected.

## Model run (in progress)

The prompt text changed (`extract-v4` → `extract-v5`), so E4's scores do not carry over. The run repeats E4's procedure: extraction on the 15 chunks, scoring, oracle review, a new graph generation and the 31 questions. An earlier attempt failed before any model call because the model server was still loading (run row 3 in the prototype database, no candidates). Results will be added here and compared with E4: precision 0.97, recall 0.68, end-to-end 19/31.

## Not covered

- Relations between entities and identifier schemes in the profile format; QA templates remain oil-well specific.
- Ontology editing, activation diff and re-run comparison (admin application, M4).
- A held-out evaluation; this uses E4's development slice.
