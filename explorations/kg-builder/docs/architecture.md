# Architecture

The contract chain is `Document -> Chunk -> Mention -> CandidateTriple -> CanonicalTriple -> ValidatedStatement -> GraphRecord`. Pydantic validation rejects unexpected fields. Evidence offsets address the original document text and must recover the stored evidence substring. Unknown temporal bounds remain null.

`build/ingest` reads corpora and BSEE tables. `build/parse` chunks text, chooses an extractor and grounds returned surfaces. `build/refine` canonicalizes relations, resolves aliases, interprets temporal triggers and validates statements. `build/publish` writes graphs and provenance. `evaluation` scores extraction, agreement and stage attribution; `serve` implements graph queries and QA. Shared contracts and conservative value parsing live in `core`; guarded LLM access lives in `runtime`.

KGGen runs in the main environment. EDC runs as a subprocess in a separate Python environment because its pinned dependencies conflict with the main stack. The adapter invokes upstream definition/canonicalization routines without modifying upstream source. A loopback gateway records exact requests and returns captured responses in mock mode. A missing recorded request is an error, never a reason to call a model.

The gateway and worker socket guards constrain runtime network access. Local embedding assets and NLTK resources must be provisioned before offline use. New inference uses the explicitly configured local service; reproduction uses fixtures only.

Sentence grounding reproduces earlier configurations. Window grounding handles abbreviation boundaries and nearby subject/object evidence. Number-aware resolution prevents merging names that differ in significant numbers. Soft validation preserves weak statements with flags in `graph.json`; `graph_strict.json` excludes flagged statements. GraphML and Neo4j are projections, not the evaluation source of truth.

The optional judge scores evidence support; it is not an independent factual oracle. QA retrieves source passages and/or graph facts, then uses a reader. Changing graph structure, surface forms or ordering can change retrieval and answers even when extraction scores improve.

JSON is authoritative. Keep data surfaces, provenance, recorded prompts, ontology definitions and request bytes unchanged when changing file paths or code names. Publication metadata mappings are exact, field-specific transformations, with archive-to-publication equivalence checks. See [design decisions](adr/README.md).
