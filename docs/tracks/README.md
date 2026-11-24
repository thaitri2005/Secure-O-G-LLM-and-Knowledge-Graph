# Track records

The first build (30 October to 17 November 2026) ran as three tracks joined by versioned files ([specification §4.5](../PROJECT_DESIGN.md#45-first-build-three-tracks-joined-by-files)). Each track keeps its own dated record of findings, decisions and design choices. The second build splits the work by data, backend, engine and frontend ([plan §2](../DEVELOPMENT_PLAN.md#2-team-split)); these records continue under the same names.

| Track | Owner | Record | Current state in one line |
|---|---|---|---|
| A. Ingestion and tables (data) | Khai | [A-ingestion](A-ingestion/README.md), which points to the [progress report](../experiments/TRACK_A_PROGRESS.md). To do: [note of 24 November](A-ingestion/note-from-track-B-2026-11-24.md) | K1 version 1 is the team's chunk package; new options from 17 November are off by default |
| B. GraphRAG engine | Tri | [B-graphrag](B-graphrag/README.md): [log](B-graphrag/log.md), survey, notes to the other tracks | Three lanes behind one interface and a coordinator over them, built and not yet measured |
| C. Storage, IDs and the run (backend) | Hung | [C-storage](C-storage/log.md): log, the [vector store comparison](C-storage/vector-store.md) and the [backend design](C-storage/backend-design.md). To do: [note of 24 November](C-storage/note-from-track-B-2026-11-24.md) | Stores loaded and checked on one laptop; not shared yet; no runner. Read-path API built on his behalf; the rest is in the [backend design](C-storage/backend-design.md) |

Entry numbers (`B-F`, `B-D`, `B-C`, `C-F`, …) are never reused or renumbered. Project-level decisions also go into [specification §13.1](../PROJECT_DESIGN.md#131-decision-register). Measurements go into [experiment records](../experiments/README.md).

What each stint accomplished, across tracks, is in the [stint reports](../reports/stints/README.md).
