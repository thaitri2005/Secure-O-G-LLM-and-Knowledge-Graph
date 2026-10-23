# Documentation completeness and verification

**Review date:** 23 October 2026<br>
**Implementation reviewed:** repository baseline `af7e0ae`, before this documentation update<br>
**Scope:** project description, architecture, technology choices, development planning, and consistency with the implementation

## Assessment

The original README and ingestion documents were useful subsystem documentation, but did not describe a complete end-to-end product. They documented PDF processing and its evaluation; ontology design, model extraction, graph persistence, review, QA, production operations, and a delivery plan were largely future component names.

The [project design](PROJECT_DESIGN.md) and [development plan](DEVELOPMENT_PLAN.md) now provide a comprehensive planning and implementation baseline for the user's confirmed target: an internal production service, delivered by three students with modest school hardware. This is **documentation coverage**, not a claim that the future platform is implemented, benchmarked, or approved for production.

## Coverage matrix

| Area | Previous coverage | Current reference |
|---|---|---|
| Product purpose, success measures, first-release boundaries | High-level README description | Design §1 |
| Users, roles, journeys, testable requirements | Mostly absent | Design §2, FR-01–FR-14 |
| Implemented behavior and source-code map | Ingestion detail existed | Design §3 plus the retained ingestion documents |
| Architecture and service boundaries | Component list | Design §4 and target architecture diagram |
| Data ownership, cross-store consistency, publication | Ingestion file publication only | Design §4, immutable graph generations and outbox |
| Extraction, review, identity resolution, conflict handling | Planned labels | Design §5 and claim lifecycle diagram |
| Concrete source-to-answer example | Absent | Design §5.6, actual AK-3 passage |
| Ontology, units, schema versions, domain adaptation | Planned ontology | Design §6 |
| Claim/evidence model and API contracts | Existing chunk schemas only | Design §7 and logical data model diagram |
| Supported QA behavior, citations, abstention | Future natural-language queries | Design §8 and sequence diagram |
| Technology roles, tradeoffs, alternatives | Parser/dependency information | Design §9, linked primary technical documentation |
| Security, cloud boundaries, retirement, retention | Local processing intention | Design §10 |
| Hardware, workload, deployment, recovery, ownership | Local setup only | Design §11 and deployment/recovery diagram |
| Evaluation, acceptance gates, traceability | Ingestion evaluation only | Design §12, G1–G9 |
| Decisions, assumptions, change control, glossary | Mostly absent | Design §13 |
| Delivery breakdown, dependencies, effort, responsibilities | Absent | Development plan §§1–3 and milestone diagram |
| Budget controls, risks, delivery cadence, handover | Absent | Development plan §§4–8 |

Seven diagrams are provided as checked-in SVGs and editable Mermaid source: current ingestion, target architecture, claim lifecycle, logical data model, QA sequence, deployment/recovery, and milestone dependencies.

## Corrections to the existing documentation

- The README now identifies domain portability as intended behavior. The current downloader restricts URLs to GDR, and current registries/document metadata require GDR fields; merely adding a non-GDR registry does not provide a working generic ingestion path.
- The README no longer promises that a `content_id` alone preserves an unambiguous citation across processing changes. It hashes normalized content, can repeat for identical passages, and changes with content. The proposed evidence contract pins document versions, runs, bundles, and spans.
- The intended network boundary is distinguished from currently enforced controls. Local conversion and disabled remote services exist; a production firewall, identity, audit, recovery, and access tests remain work to implement.
- Ingestion evaluation is explicitly distinguished from graph extraction and QA evaluation. Historical parser metrics have not been presented as new platform benchmarks.

## Verification performed for this update

| Check | Result and practical limit |
|---|---|
| Current code/configuration inspection | CLI commands, registry constraints, parser settings, provenance IDs, caches, publication behavior, schemas, and dependency declarations checked |
| Committed artifact integrity | All **9** entries in `data/processed/SHA256SUMS` match the current files |
| Corpus inventory | **3** document records, **155** physical pages, **372** chunks (**237** text / **135** table), **99** shared table records |
| JSON Schema validation | All committed main-bundle chunk, full-chunk, table, and document records pass their corresponding Draft 2020-12 schema |
| Evidence structure | All paired chunk/sidecar fields agree; canonical text slices match chunk text; content IDs recompute correctly; all region boxes fit their referenced page geometry |
| Documentation links and anchors | Local file links, internal heading anchors, image targets, and balanced code fences checked after editing |
| Diagrams | All **7** parsed and rendered with Mermaid **11.17.2**; rendered screenshots visually inspected and wide layouts adjusted |
| Plan arithmetic | Milestone estimates sum to **576 hours**; **144 hours** contingency gives **720 hours**, equal to 3 students × 12 hours × 20 weeks |
| Change scope | Documentation and diagram assets only; application source, schemas, configurations, published data, and dependency locks unchanged |

These checks do **not** constitute a fresh PDF conversion or reproduction of every historical evaluation metric. This checkout has no raw-PDF/Docling conversion cache, and Docling is not installed in the available Python environment. The full ingestion unit suite and fresh conversion were therefore not rerun for this documentation-only change. Existing detailed conversion/evaluation results remain attributed to [the ingestion evaluation report](ingestion-evaluation.md).

No LLM, graph service, login integration, production host, or cloud deployment was installed as part of this update. Temporary diagram-rendering tools were used outside the project dependency environment; their dependencies are not added to the application lock.

## Remaining project decisions

The documents can guide implementation now. The following inputs still need real project decisions at the gates stated in the plan: exact GPU/host allocation and whether persistent hosting is permitted; team availability/deadline; spending ceiling; product/domain reviewer; institutional login/network/backup integration; per-document access needs; model selection after benchmarking; and the post-project operator/support policy.

The plan uses a 4080 SUPER-class baseline and treats A100 access as optional. It contains no hardware purchase or paid-cloud commitment. Its 20-week example is conditional on weekly effort and scope, not a promised delivery date. A future production release is complete only after the implementation and acceptance gates have evidence and the product/operating owners accept their responsibilities.
