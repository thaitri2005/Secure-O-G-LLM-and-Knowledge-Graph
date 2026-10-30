# Overview

kg-builder turns documents into statements with source evidence, then evaluates how extraction and refinement affect graph quality and question answering. Its central output is a JSON graph with documents, chunks, entities and statements. Every statement retains evidence offsets, source identity, temporal fields and extraction provenance.

The general-text path supports KGGen, EDC and configuration-based routing. The BSEE path adds an explicit well-operation ontology, typed quantities, guided extraction, deterministic table ingestion and a frozen LLM-annotated benchmark. The same export and evaluation contracts connect these paths.

The shipped evidence includes recorded requests and responses, gold annotations, predictions, small graphs, score files and the expected-results ledger. Bulk raw downloads, database stores, environments, model caches and cloned dependencies are local prerequisites rather than publication contents. Generated reference layouts are disposable copies under `runs/reference/`.

Use [usage](usage.md) to run the project, [architecture](architecture.md) to understand the contracts and [results](results.md) to assess the evidence. The project supports reproducible experiments; its small benchmark results do not establish general extraction accuracy or production readiness.
