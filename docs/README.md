# Documentation

**Current direction (24 November 2026):** a **GraphRAG application for drilling reports** (end-of-well and daily drilling reports). A coordinator sends each question to a lane: text passages, facts about a well, or events over time, the last two held in one graph. It uses open-weight models of about 7B or smaller and never commercial APIs; it links stores and documents through one ID scheme; and it is delivered as a full application with chat and administration. The basis is the [28 October](requirements/supervisor-meeting-2026-10-28.md) and [9 November](requirements/supervisor-meeting-2026-11-09.md) supervisor meetings (specification D-36 to D-63) and the design choices of 24 November (D-64 to D-67).

**Where the project stands:** the first build is closed. Chunk packages, the stores and the engine exist as three separate parts. The second build connects them behind one application.

| To find out… | Read |
|---|---|
| What is being built now, and who does what | [Plan §7, "What to do now"](DEVELOPMENT_PLAN.md#7-what-to-do-now) |
| How the system is designed | [Specification §4](PROJECT_DESIGN.md#4-target-architecture) and [§8](PROJECT_DESIGN.md#8-question-answering) |
| What runs today and how it scores | [Specification §8.4](PROJECT_DESIGN.md#84-what-the-first-build-runs-today) |
| What each part of the team has found | [Track records](tracks/README.md) |
| What the supervisor asked for | [Meeting digests](requirements/README.md) |

## Document hierarchy

The [project specification](PROJECT_DESIGN.md) is the **single source of truth**. Every other document is an input to it, derived from it, or supports it, and it wins any disagreement.

| Kind | Document | Read it for |
|---|---|---|
| **Inputs** | [Stakeholder requirements](requirements/README.md) | VPI's documents (SR-01 to SR-18) and the supervisor meetings: [9 November](requirements/supervisor-meeting-2026-11-09.md) and [28 October](requirements/supervisor-meeting-2026-10-28.md) (current direction), and [7 October](requirements/supervisor-meeting-2026-10-07.md) (partly superseded) |
| **Source of truth** | [Project specification and system design](PROJECT_DESIGN.md) | Scope, architecture and stores, ID scheme, tables, the coordinator and lanes, the graph model, models and compute, acceptance gates, decisions, open questions |
| **Derived** | [Development plan](DEVELOPMENT_PLAN.md) | Current status, how the first build closed, roles, milestones, the task list, risks |
| Supporting | [Data sources](DATA_SOURCES.md) | The public data: BSEE well files, end-of-well reports (AK-3 first), daily drilling reports |
| Supporting | [Components](components/) | How each implemented subsystem works: [document ingestion](components/corpus-ingestion.md), [structured-data import](components/dataset-import.md), [entity registry](components/entity-registry.md). Earlier pipelines kept for reproduction: [PDF ingestion](components/pdf-ingestion.md), [OCR ingestion](components/ocr-ingestion.md), [BSEE ingestion](components/bsee-ingestion.md) |
| Supporting | [Track records](tracks/README.md) | Each track's findings, decisions and design choices, logged the same day: [A, ingestion](tracks/A-ingestion/README.md), [B, GraphRAG engine](tracks/B-graphrag/README.md), [C, storage](tracks/C-storage/log.md) |
| Supporting | [Experiments](experiments/README.md) | Measurements, one record per experiment (E1–E31) |
| Supporting | [Reports](reports/README.md) | What was sent to the supervisors: the [project report of 9 November](reports/PROJECT_REPORT_2026-11-09.md) |
| Supporting | [Related work](references.md) | Papers, GraphRAG repositories and model candidates |
| Historical | [Repository assessment, 27 October](REPOSITORY_REVIEW_2026-10-27.md) · [Progress report, 27 October](reports/KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.md) | Snapshots from before the 28 October direction |
| Assets | [Diagrams](diagrams/README.md) | SVG exports and how to regenerate them |

Reading order for a new team member:

1. the [9 November](requirements/supervisor-meeting-2026-11-09.md) and [28 October](requirements/supervisor-meeting-2026-10-28.md) meeting digests;
2. the specification's §1 and §3;
3. the specification's §4.1, §4.6 and §8.1, then the plan's §7 for your role;
4. your track's record in [tracks/](tracks/README.md);
5. the data sources and the component guide for your area.

## Conventions

- **Implemented** means code, tests and a verification record exist in this repository. **Planned** or **proposed** means design intent only.
- Change the specification first, then the plan. A plan or guide must not introduce scope the specification does not contain.
- When the direction changes, **remove** the superseded design text instead of keeping old and new side by side. Record the removal in the meeting digest and move the old decision to the superseded table in specification §13.1.
- Log every finding, decision, design choice and experiment the same day in the track log ([example](tracks/B-graphrag/log.md)). Project-level decisions also go into specification §13.1.
- Measurements live in experiment records. Do not copy numbers between documents; link to the experiment that owns them.
- When behavior changes, update the component guide and specification §3 in the same change.
- Supervisor direction is recorded as a meeting digest in `requirements/` and as decisions in specification §13.1; unanswered questions stay in §13.2.
- Reporting to the supervisor is light: short group-chat updates, and two or three slides of architecture with one sample walked through the pipeline (D-46, 9 November meeting). Long written reports are not the norm.
- Diagram sources are the Mermaid blocks in the documents; the SVGs are generated from them ([how](diagrams/README.md)).
