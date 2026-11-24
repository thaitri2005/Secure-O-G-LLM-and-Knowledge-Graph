# Reports

## Stint reports

One per stint, short, for the supervisor: [stints/](stints/README.md).

- **Latest: [10 to 24 November 2026](stints/STINT_REPORT_2026-11-24.md).** The second build designed; the coordinator, the backend and the application built; not yet run with a real model.
- [5 November 2026](stints/STINT_UPDATE_2026-11-05.md): Track B's status, in Vietnamese.

## Project report, 9 November 2026

[`PROJECT_REPORT_2026-11-09.md`](PROJECT_REPORT_2026-11-09.md), in English, for the supervisors: purpose and scope, how the project got here, the target architecture, the first build's three tracks in detail (ingestion, the GraphRAG engine with its two graphs, storage), results, roadmap and what the team needs. Diagrams are Mermaid in the text. A shared web copy is at https://claude.ai/artifact/J3cK4LfXiAfKD7J3ZSt3CE; this file is the record.

## Draft: resource request, 24 November 2026

[`RESOURCE_REQUEST_2026-11-24.md`](RESOURCE_REQUEST_2026-11-24.md): what the second build needs to run where domain experts can reach it (a server for the stores and the application, a hosted open-weight model for the demo), what it costs, and what is asked of the supervisor: US$10 certain, at most US$160. A draft until Hung confirms the server size and the team sends it. Prices are list prices found that day.

## Slides for the professor's review, 11 November 2026

Six slides, "GraphRAG Architecture Today", made in Canva on 12 November after the [9 November meeting](../requirements/supervisor-meeting-2026-11-09.md) asked for two or three slides of architecture instead of long text. The PDF is about 10 MB and is not committed; Tri keeps it. Its content is the architecture of [specification §8.4](../PROJECT_DESIGN.md#84-what-the-first-build-runs-today).

## Historical: progress report, 27 October 2026

**Historical snapshot (27 October 2026).** This report predates the [28 October direction](../requirements/supervisor-meeting-2026-10-28.md): GraphRAG, open models of about 7B, VLM parsing and a full application. Its "builder first, QA second" framing, OCR-engine plan and research workstream are superseded; see the [specification](../PROJECT_DESIGN.md) for the current design. The supervisor asked for lighter reporting from now on: a weekly slide plan and short group-chat updates (D-46), not reports of this length.

[Vietnamese report](KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.md) · [PDF](../../output/pdf/KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.pdf)

This is one unified project-status report covering ingestion, method evaluation, graph construction, prototype QA and next steps. The original report is the content baseline; status updates and new findings are incorporated into the relevant sections. Problems, evaluation limits, machine constraints and costs are consolidated with concise next steps in section 6. It keeps Vietnamese narrative and English technical terms. Six vector figures illustrate current paths, target architecture, AK-3 extraction/QA, OCR comparison, research comparisons and the next milestone alongside the detailed results. Figures distinguish implemented/prototype/planned behavior and preserve evaluation denominators.

`figures/` contains SVGs for Markdown; the PDF embeds the same diagrams as vectors. Figure data and layout are in [`scripts/render_progress_report.py`](../../scripts/render_progress_report.py). This is a documentation renderer, not part of the application runtime.

To regenerate in the existing Windows checkout, install ReportLab separately from the runtime lock, then run the renderer. It also uses the checkout's `markdown-it-py`, `pypdf` and `pypdfium2` and Windows Arial fonts:

```powershell
.\.venv\Scripts\python -m pip install --target tmp/pdf-deps --no-deps reportlab==5.1.0
.\.venv\Scripts\python scripts/render_progress_report.py --deps tmp/pdf-deps
```

The renderer writes the report PDF, SVGs and temporary page images in `tmp/report-qa/`; it verifies that report text is preserved in the PDF. Inspect every rendered page after changes. Diagram labels and source metrics must be updated together. Temporary rendering dependencies/images are not deliverables and should not be committed.
