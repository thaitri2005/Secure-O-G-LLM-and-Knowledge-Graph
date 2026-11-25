# Stint reports

One report per stint of one to two weeks: what was asked, what was done and by whom, how the system works now, what was learned, what is weak, and what the team needs. Written for the supervisor, with diagrams and one question walked through the system ([9 November meeting](../../requirements/supervisor-meeting-2026-11-09.md), §6).

| Stint | Report | State | Language |
|---|---|---|---|
| 10 to 27 November 2026 | [STINT_REPORT_2026-11-27.md](STINT_REPORT_2026-11-27.md) · [PDF](STINT_REPORT_2026-11-27.pdf): the second build designed, built and run with the real model; the coordinator and the answers about causes measured; the path for an expert's input | **Draft**, updated until the stint ends on 27 November | English |
| 30 October to 5 November 2026 | [STINT_UPDATE_2026-11-05.md](STINT_UPDATE_2026-11-05.md): Track B's status for the supervisor, E23 to E29 | Sent | Vietnamese |

## Updating a report and its PDF

The Markdown file is the source. The PDF and the diagrams are made from it:

```powershell
python scripts/stint_figures.py                                                   # redraws figures/*.svg
python scripts/render_stint_report.py docs/reports/stints/STINT_REPORT_2026-11-27.md   # writes the PDF beside it
```

- **Diagrams** (`figures/architecture.svg`, `deployment.svg`, `question-flow.svg`, `knowledge-graph.svg`, `expert-path.svg`) are drawn by `scripts/stint_figures.py`. Change the text there and run it; do not edit the SVG files by hand.
- **Screenshots** (`figures/app-*.png`) are of the application in examples mode (`npm run dev:examples` in `frontend/`), at 1360 pixels wide and twice the pixel density. Two are not: `app-ai-answer.png` and `app-page.png` were taken on the stores with the real model answering.
- On Linux the PDF needs a Chromium at `/usr/bin/chromium` or `/opt/pw-browsers/chromium`, or `REPORT_BROWSER` set to one.
- The PDF needs Microsoft Edge or Chrome on the machine; nothing else is installed.
- Commit the Markdown, the figures and the PDF together, so the PDF never disagrees with its source.

## Writing the next one

- Name the file `STINT_REPORT_<date of the stint's last day>.md` and add a row above. Start it as a draft and say so on its first line.
- Write in the third person: "the team", "anh Tuấn asked". No "you", "I" or "we".
- Keep it short: about 3,500 words; a table or a figure before a paragraph.
- Say what each person built, in words a reader outside the team understands. Link to the logs and experiment records for the detail.
- Explain how the system works with a diagram, not a list of module names.
- State the weak points plainly, and what is not done.
- Every number names what it was measured on. Questions written by the team are never called an evaluation.
- English unless Tri asks for Vietnamese; Vietnamese reports keep technical terms in English.

Other reports stay one level up, in [`docs/reports/`](../README.md): the project report, the resource request, slides, and the historical progress report.
