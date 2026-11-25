# Track A: ingestion and tables

**Owner (from 5 November 2026):** Khai · **Scope:** [specification §5.1](../../PROJECT_DESIGN.md#51-stages) stages 1 to 4 and §5.10; publishes the chunk package K1

This page was added by Track B on 24 November 2026 so that all three tracks can be found in one place. It only points to Track A's own files and changes none of them. Khai decides whether to keep a dated log here, as Tracks B and C do ([plan](../../DEVELOPMENT_PLAN.md#7-what-to-do-now), task D5).

| File | What it holds |
|---|---|
| **[Note of 24 November](note-from-track-B-2026-11-24.md)** | **What the second build needs from data, in order: the demo release first** |
| [Track A progress report](../../experiments/TRACK_A_PROGRESS.md) | What is implemented, what was measured on which data, and what is open, as of 9 November |
| [E30: K1 version 1 candidate](../../experiments/E30-k1-version-1-candidate.md) | The package that became the team's interface (D-54, D-57) |
| [Document ingestion guide](../../components/corpus-ingestion.md) | How the pipeline and its options work, including those added on 17 November |
| [Dependencies](../../components/dependencies.md), [model provenance](../../components/model-provenance.md) | Packages, licences and model files |
| [Quality ledger](../../components/quality-ledger.md) | The QA sidecar |
| [Note from Track B](../B-graphrag/note-for-track-A-daily-reports.md) | What the engine needs from K1 |

**The options of the 17 November merge** (table joining across pages, section context, form recognition, label-value repair, page orientation) **were measured on the demo package on 25 November** ([E62](../../experiments/E62-track-a-option-measurements.md), log A-F23 to A-D08): section context and grid recovery are on, table joining stays as shipped, the others are off.
