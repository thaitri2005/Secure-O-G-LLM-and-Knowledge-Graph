# Documentation

**Current direction:** a knowledge-graph builder (domain-agnostic pipeline and admin application, user-supplied ontology), with one English oil-well use case. Builder first, QA second, access control later. The [7 October supervisor meeting](requirements/supervisor-meeting-2026-10-07.md) is the basis (specification D-28 to D-35); [§4.4](PROJECT_DESIGN.md#44-core-and-domain-profile-boundary) defines the core/profile boundary and D-26/D-27 the team's scope.

## Document hierarchy

The [project specification](PROJECT_DESIGN.md) is the **single source of truth**. Every other document is an input to it, derived from it, or supports it, and it wins any disagreement.

| Kind | Document | Read it for |
|---|---|---|
| **Inputs** | [Stakeholder requirements](requirements/README.md) | What VPI asked for: digest of the capstone proposal and the KGinEP document, requirement IDs SR-01 to SR-18; the supervisor's [7 October direction](requirements/supervisor-meeting-2026-10-07.md) |
| **Source of truth** | [Project specification and system design](PROJECT_DESIGN.md) | Scope, the three-layer target, requirement decisions, architecture, data model, extraction, QA, security, operations, acceptance gates, decisions, open questions |
| **Derived** | [Development plan](DEVELOPMENT_PLAN.md) | Current status, milestones, ownership, estimates, risks, next backlog |
| Supporting | [Data sources](DATA_SOURCES.md) | The public proxy data (BSEE well files, AK-3 and other end-of-well reports): content, terms, quality findings, refresh |
| Supporting | [Components](components/) | How each implemented subsystem works and is run. Current pipelines: [document ingestion](components/corpus-ingestion.md) (any format, OCR, Vietnamese) and [structured-data import](components/dataset-import.md) (mapping-driven). Earlier pipelines kept for reproduction: [PDF ingestion](components/pdf-ingestion.md), [OCR ingestion](components/ocr-ingestion.md), [BSEE ingestion and linked graph](components/bsee-ingestion.md) |
| Supporting | [Experiments](experiments/README.md) | Repository measurements, one record per experiment (E1–E9); E9 records the review verification and open defects |
| Supporting | [Repository assessment](REPOSITORY_REVIEW_2026-10-27.md) | Code findings, cost/scope/security assessment and implementation priorities; fixes remain open |
| Reporting | [Progress report 27 October](reports/KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.md) · [PDF](../output/pdf/KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.pdf) | Unified Vietnamese project-status report covering ingestion, method evaluation, graph construction, prototype QA and next steps |
| Supporting | [Related work](references.md) | Papers and resources from the supervisor, access status, takeaways |
| Assets | [Diagrams](diagrams/README.md) | SVG exports and how to regenerate them |

Reading order for a new team member: the 7 October meeting digest, the specification's §1, the development plan's current status, data sources, then the component guide for the area you work on.

## Conventions

- **Implemented** means code, tests and a verification record exist in this repository. **Proposed** or **planned** means design intent only.
- The progress report presents the project as one body of work. Keep dataset, configuration, metric and test-suite scope attached to each experiment; distinguish completed workstreams from planned integration.
- Change the specification first, then the plan. A plan or guide must not introduce scope the specification does not contain.
- Measurements live in experiment records. Don't copy numbers between documents; link to the experiment that owns them.
- When behavior changes, update the component guide and specification §3 in the same change.
- Supervisor feedback that changes scope is recorded as a decision (specification §13.1); unanswered questions stay in §13.2.
- Diagram sources are the Mermaid blocks in the documents; the SVGs are generated from them ([how](diagrams/README.md)).
