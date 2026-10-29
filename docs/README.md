# Documentation

**Current direction (28 October 2026):** a **GraphRAG application for drilling reports** (end-of-well and daily drilling reports), built on an existing open-source GraphRAG pipeline. It uses open-weight models of about 7B or smaller and never commercial APIs; it parses pages and tables with VLMs; it links stores and documents through one ID scheme; and it is delivered as a full application with chat and administration. Ingestion and data organization come first, on one document. The [28 October supervisor meeting](requirements/supervisor-meeting-2026-10-28.md) is the basis (specification D-36 to D-47). [Its §13](requirements/supervisor-meeting-2026-10-28.md#13-effect-on-the-documentation) lists what was removed from the earlier design.

## Document hierarchy

The [project specification](PROJECT_DESIGN.md) is the **single source of truth**. Every other document is an input to it, derived from it, or supports it, and it wins any disagreement.

| Kind | Document | Read it for |
|---|---|---|
| **Inputs** | [Stakeholder requirements](requirements/README.md) | VPI's documents (SR-01 to SR-18) and the supervisor meetings: [28 October](requirements/supervisor-meeting-2026-10-28.md) (current direction) and [7 October](requirements/supervisor-meeting-2026-10-07.md) (partly superseded) |
| **Source of truth** | [Project specification and system design](PROJECT_DESIGN.md) | Scope, architecture and stores, ID scheme, tables, ontology injection, GraphRAG retrieval, models and compute, acceptance gates, decisions, open questions |
| **Derived** | [Development plan](DEVELOPMENT_PLAN.md) | Current status, roles (data, backend, frontend), milestones, this week's tasks, risks, backlog |
| Supporting | [Data sources](DATA_SOURCES.md) | The public data: BSEE well files, end-of-well reports (AK-3 first), daily drilling reports |
| Supporting | [Components](components/) | How each implemented subsystem works: [document ingestion](components/corpus-ingestion.md), [structured-data import](components/dataset-import.md), [entity registry](components/entity-registry.md). Earlier pipelines kept for reproduction: [PDF ingestion](components/pdf-ingestion.md), [OCR ingestion](components/ocr-ingestion.md), [BSEE ingestion](components/bsee-ingestion.md) |
| Supporting | [Experiments](experiments/README.md) | Measurements, one record per experiment (E1–E13) |
| Supporting | [Related work](references.md) | Papers, GraphRAG repositories and model candidates |
| Historical | [Repository assessment, 27 October](REPOSITORY_REVIEW_2026-10-27.md) · [Progress report, 27 October](reports/KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.md) | Snapshots from before the 28 October direction; their open code findings are tracked in the plan backlog |
| Assets | [Diagrams](diagrams/README.md) | SVG exports and how to regenerate them |

Reading order for a new team member:

1. the [28 October meeting digest](requirements/supervisor-meeting-2026-10-28.md);
2. the specification's §1 and §3;
3. the development plan's current status and your role's milestone;
4. the data sources;
5. the component guide for your area.

## Conventions

- **Implemented** means code, tests and a verification record exist in this repository. **Planned** or **proposed** means design intent only.
- Change the specification first, then the plan. A plan or guide must not introduce scope the specification does not contain.
- When the direction changes, **remove** the superseded design text instead of keeping old and new side by side. Record the removal in the meeting digest and move the old decision to the superseded table in specification §13.1.
- Measurements live in experiment records. Do not copy numbers between documents; link to the experiment that owns them.
- When behavior changes, update the component guide and specification §3 in the same change.
- Supervisor direction is recorded as a meeting digest in `requirements/` and as decisions in specification §13.1; unanswered questions stay in §13.2.
- Reporting to the supervisor is light: a weekly slide plan and short group-chat updates (D-46). Long written reports are not the norm; the 27 October report is a historical snapshot.
- Diagram sources are the Mermaid blocks in the documents; the SVGs are generated from them ([how](diagrams/README.md)).
