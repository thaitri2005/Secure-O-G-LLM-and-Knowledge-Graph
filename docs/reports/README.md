# Progress report

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
