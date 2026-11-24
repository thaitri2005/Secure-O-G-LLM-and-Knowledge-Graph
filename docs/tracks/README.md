# Track records

The first build (30 October to 17 November 2026) ran as three tracks joined by versioned files ([specification §4.5](../PROJECT_DESIGN.md#45-first-build-three-tracks-joined-by-files)). Each track keeps its own dated record of findings, decisions and design choices. The second build splits the work by data, backend, engine and frontend ([plan §2](../DEVELOPMENT_PLAN.md#2-team-split)); these records continue under the same names.

| Track | Owner | Record | Current state in one line |
|---|---|---|---|
| A. Ingestion and tables (data) | Khai | [A-ingestion](A-ingestion/README.md), which points to the [progress report](../experiments/TRACK_A_PROGRESS.md) | K1 version 1 is the team's chunk package; new options from 17 November are off by default |
| B. GraphRAG engine | Tri | [B-graphrag](B-graphrag/README.md): [log](B-graphrag/log.md), survey, notes to the other tracks | Three lanes run; the coordinator is designed, not built |
| C. Storage, IDs and the run (backend) | Hung | [C-storage](C-storage/log.md): log and the [vector store comparison](C-storage/vector-store.md) | Stores loaded and checked on one laptop; not shared yet; no runner |

Entry numbers (`B-F`, `B-D`, `B-C`, `C-F`, …) are never reused or renumbered. Project-level decisions also go into [specification §13.1](../PROJECT_DESIGN.md#131-decision-register). Measurements go into [experiment records](../experiments/README.md).
