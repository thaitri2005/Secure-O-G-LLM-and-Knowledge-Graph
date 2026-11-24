# Track records

The first build (30 October to 17 November 2026) ran as three tracks joined by versioned files ([specification §4.5](../PROJECT_DESIGN.md#45-first-build-three-tracks-joined-by-files)). Each track keeps its own dated record of findings, decisions and design choices. The second build splits the work by data, backend, engine and frontend ([plan §2](../DEVELOPMENT_PLAN.md#2-team-split)); these records continue under the same names.

| Track | Owner | Record | Current state in one line |
|---|---|---|---|
| A. Ingestion and tables (data) | Khai | [A-ingestion](A-ingestion/README.md): a [log](A-ingestion/log.md) (a draft for Khai to correct) and the [progress report](../experiments/TRACK_A_PROGRESS.md). To do: [note of 24 November](A-ingestion/note-from-track-B-2026-11-24.md) | K1 version 1 is the team's chunk package. A demo release with the non-productive-time report builds with one command; the options of 17 November are still to be measured |
| B. GraphRAG engine | Tri | [B-graphrag](B-graphrag/README.md): [log](B-graphrag/log.md), survey, notes to the other tracks | Four lanes behind one interface and a coordinator over them, reading files or the stores; a backend and a frontend on top. Built, run with stand-in models, not yet measured: the team has no GPU of its own |
| C. Storage, IDs and the run (backend) | Hung | [C-storage](C-storage/log.md): log, the [vector store comparison](C-storage/vector-store.md), the [backend design](C-storage/backend-design.md) and the [server runbook](C-storage/server-runbook.md). To do: [note of 24 November](C-storage/note-from-track-B-2026-11-24.md) | One command loads a release into PostgreSQL and Neo4j; the application runs on the stores behind one password, on laptops. No server yet |

Entry numbers (`B-F`, `B-D`, `B-C`, `C-F`, …) are never reused or renumbered. Project-level decisions also go into [specification §13.1](../PROJECT_DESIGN.md#131-decision-register). Measurements go into [experiment records](../experiments/README.md).

What each stint accomplished, across tracks, is in the [stint reports](../reports/stints/README.md).
