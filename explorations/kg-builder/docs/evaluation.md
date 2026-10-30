# Evaluation

`results/expected_results.json` preserves captured published values. Counts compare exactly; floating-point values compare within absolute tolerance `1e-9`; null means undefined. Historical inference costs, execution counters and external baselines are explicitly classified. They are not assertions about replay speed on a new computer.

## Pipeline levels

| Level | Added operation |
| --- | --- |
| A0 | Extraction and evidence grounding |
| A1 | Entity resolution |
| A2 | Relation canonicalization |
| A3 | Temporal interpretation |
| A4 | Deterministic validation |
| A5 | Evidence judge |

These are method levels, not development stages. Their exact flags and historical defaults belong to each configuration. Full and strict exports are separate views; a filtering change must not silently replace one with the other.

## Scoring

WebNLG uses the pinned EDC evaluator, including strict, exact, partial, entity-type and full-triple measures. These measures have different matching semantics. Showcase checks test known graph properties. MINE compares recorded judge decisions on three essays and 45 queries. QA uses the pinned HippoRAG answer metric on ten questions, reporting EM and token F1 alongside retrieval information.

BSEE separates table-silver, deterministic rule comparisons, LLM-annotated gold and descriptive self-consistency. Silver agreement is not accuracy. Gold matching uses conservative values and units: L1 measures value recovery, L2 adds relation identity and L3 adds subject/qualifier compatibility. Positive, negative, uncertain and out-of-ontology facts have distinct scoring roles. `time` is unscored; unsupported quantities do not receive guessed units or references.

IAA is recomputed from the two annotations with symmetric matching. It measures agreement, not correctness or a human accuracy ceiling. The labels were produced by two independent LLM annotators of different model families and adjudicated by an LLM. The adjudicator shares annotator A's family; v2 partial-item participation was 91 for A and 27 for B, with 9 edited decisions. Accepting both participates in both counts. See [annotation methodology](annotation-guideline.md).

## Comparison policy

The pre-registered primary endpoint is full-export L2 F1. An improvement is confirmed only when the paired bootstrap 95% interval lower bound is strictly positive. A sign-test p-value or positive secondary strict-export interval does not replace this criterion. Both published primary comparisons are not confirmed. Development selection is in-sample; test results must be interpreted with the selection history and small sample sizes.

**v1 and v2 scores are not comparable**: they use different corpora and conversion behavior. The v1 scored test subset has 50 documents, while the full test split has 75; the 25 reserved documents were not run through the extraction comparison. v2 has 65 development and 155 test documents. Unreadable documents are counted but excluded from scoring.

## Reproduction

Quick reproduction derives score tables from shipped labels, predictions and graphs. Full reproduction additionally rebuilds published configurations with `--mock`, checks zero fixture misses and compares graph content. Only exact declared metadata mappings may affect canonical JSON comparison; unaffected graphs remain byte-equal. Fixture request keys and prompt bytes are invariant. Optional table rebuilding and Neo4j loading are documented separately and never part of default reproduction.
