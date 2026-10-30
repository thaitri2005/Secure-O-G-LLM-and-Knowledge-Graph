# Annotation methodology

This is an **LLM-annotated benchmark**, not human expert labels. Two independent LLM annotators from different model families labelled every chunk; an LLM adjudicator resolved disagreements. The stored role IDs are `annotator_a`, `annotator_b` and `adjudicator`. Anonymous A/B packet keys do not identify the annotator family.

The adjudicator shares annotator A's model family. On v2 partial disagreements, family participation was 91 for A, 27 for B and 9 edited decisions. Accepting both contributes to both counts. These counts show a preference and do not establish impartiality. Anonymisation and ordering checks provide procedural blindness, not a guarantee of independence. In a v1 correction, one annotator saw parser code. No domain expert validated the guideline.

The v1 adjudicated set contains 456 facts: 363 positive, 22 negative, 32 uncertain and 39 other. v2 contains 1,057: 727 positive, 82 negative, 100 uncertain and 148 other. The v1 scored subset L2 IAA is 0.8790697674418605; v2 test L2 IAA is 0.8538622129436325. Agreement does not prove correctness. **v1 and v2 scores are not comparable**.

## Rules and boundaries

Annotate only facts explicitly supported by the chunk. Use exact substrings and occurrence indices; evidence must contain the object and any explicit subject. Only the report well can be implicit. Never infer missing measurements, units, years or entities from external tables or background knowledge. Clear facts outside the ontology use `other`; they are retained and counted without becoming ordinary scored positives.

Preserve source characters and geological names exactly. The authoritative relation definitions, qualifier sets and examples are in each frozen protocol and `contracts/ontology/bsee.yaml`. The protocol introduction was reworded for publication; annotation rules and examples were not changed. Publication seals supersede the archival freeze chain with label content identical under the role-ID mapping.

Dates use US month/day/year order, with `/` or `-` consistently in both positions. Two-digit years 00-49 map to 2000-2049, and 50-99 to 1950-1999. Recognized ISO, month-name and year forms retain their supported precision. Missing-year, mixed-separator, invalid and unlisted forms return a null ISO date with `partial` precision; there is no whitelist restricting partial date surfaces. Never borrow a year from another part of the chunk. **`time` is unscored.** Adjudication retained 25 agreed facts with differing times in v1 and 15 in v2.

## Evaluation corrections

The frozen tooling was corrected twice before scoring. Corrections aligned date separators, composite-size parsing and pressure context with the guideline. Later corrections covered symmetric IAA, depth references in qualifiers, compact units, status phrases and deterministic rule annotations, and fixed silver contradictions and policy binding. These changes corrected evaluation behavior; they did not license rewriting labels to improve extraction scores. Historical correction chains are not distributed; publication verification binds the current evaluator inputs.

Unreadable chunks are counted but not scored. A chunk containing a person name is marked unreadable with no facts and without copying that name. The selected narratives were screened for PII before freezing; the screen is not a guarantee of absence. See [evaluation](evaluation.md) for matching levels, confidence intervals and the confirmation criterion.
