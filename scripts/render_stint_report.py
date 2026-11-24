"""Render a stint report (Markdown with Mermaid diagrams and images) to a PDF beside it.

    python scripts/render_stint_report.py docs/reports/stints/STINT_REPORT_2026-11-27.md

The Markdown file stays the source. Each Mermaid block is drawn with mermaid-cli (through npx, as
docs/diagrams/README.md describes), the page is laid out as HTML, and a Chromium-based browser prints it to PDF.
Needs: markdown-it-py (in the lock file), Node.js for npx, and Microsoft Edge or Chrome. No model, no network
beyond npx fetching mermaid-cli the first time.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from markdown_it import MarkdownIt

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]
MERMAID = {
    "theme": "base",
    "themeVariables": {
        "fontFamily": "Segoe UI, Arial, sans-serif", "fontSize": "15px", "primaryColor": "#e6effe",
        "primaryBorderColor": "#1d5fd6", "primaryTextColor": "#0f1e33", "lineColor": "#5d6d85",
        "clusterBkg": "#f5f8fc", "clusterBorder": "#c9d4e3", "edgeLabelBackground": "#ffffff",
        "tertiaryColor": "#f5f8fc",
    },
    "flowchart": {"htmlLabels": True, "curve": "basis", "padding": 14, "nodeSpacing": 34, "rankSpacing": 46},
}
CSS = """
@page { size: A4; margin: 16mm 15mm 17mm; }
* { box-sizing: border-box; }
body { margin: 0; color: #33445c; font: 10.5pt/1.55 "Segoe UI", Arial, sans-serif; }
h1 { margin: 0 0 4pt; color: #0f1e33; font-size: 23pt; line-height: 1.15; letter-spacing: -0.02em; }
h2 { margin: 18pt 0 6pt; padding-top: 10pt; border-top: 1.5pt solid #dde5f0; color: #0f1e33; font-size: 15pt;
     page-break-after: avoid; break-after: avoid-page; }
h3 { margin: 13pt 0 4pt; color: #0f1e33; font-size: 11.5pt; page-break-after: avoid; }
p { margin: 0 0 7pt; }
ul, ol { margin: 0 0 7pt; padding-left: 16pt; }
li { margin-bottom: 2.5pt; }
strong { color: #0f1e33; }
a { color: #174bab; text-decoration: none; }
code { padding: 0 2pt; border-radius: 3pt; background: #eef3fa; font: 9pt Consolas, monospace; }
table { width: 100%; margin: 4pt 0 10pt; border-collapse: collapse; font-size: 9.5pt; }
tr { page-break-inside: avoid; }
thead { display: table-header-group; }
th { padding: 5pt 6pt; border-bottom: 1.2pt solid #0f1e33; background: #eef3fa; color: #0f1e33; text-align: left; }
td { padding: 5pt 6pt; border-bottom: 0.6pt solid #dde5f0; vertical-align: top; }
.figure { margin: 8pt 0 4pt; padding: 8pt; border: 0.8pt solid #dde5f0; border-radius: 8pt; background: #fff;
          text-align: center; page-break-inside: avoid; }
.figure svg { max-width: 100%; height: auto; }
.figure img { max-width: 100%; max-height: 172mm; border-radius: 5pt; }
.figure.shot { padding: 3pt; }
.figure.shot img { max-height: 118mm; }
.figure + p { page-break-before: avoid; }
.status { margin: 8pt 0 12pt; padding: 8pt 10pt; border-left: 3pt solid #f0a13a; border-radius: 4pt;
          background: #fff1da; color: #0f1e33; }
"""


def browser() -> str:
    found = os.environ.get("REPORT_BROWSER") or next((b for b in BROWSERS if Path(b).is_file()), None)
    if not found:
        raise SystemExit("No Edge or Chrome found. Set REPORT_BROWSER to a Chromium-based browser.")
    return found


def draw(source: str, work: Path, number: int) -> str:
    """One Mermaid block as inline SVG."""
    (work / "mermaid.json").write_text(json.dumps(MERMAID), encoding="utf-8")
    (work / "puppeteer.json").write_text(json.dumps({"executablePath": browser()}), encoding="utf-8")
    src, out = work / f"d{number}.mmd", work / f"d{number}.svg"
    src.write_text(source, encoding="utf-8")
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise SystemExit("npx (Node.js) is needed to draw the diagrams.")
    done = subprocess.run([npx, "-y", "@mermaid-js/mermaid-cli@11.17.0", "-i", str(src), "-o", str(out), "-c",
                           str(work / "mermaid.json"), "-p", str(work / "puppeteer.json"), "-b", "transparent",
                           "-I", f"stint{number}"], capture_output=True, text=True,
                          env={**os.environ, "PUPPETEER_SKIP_DOWNLOAD": "1"})
    if not out.is_file():
        raise SystemExit(f"Diagram {number} could not be drawn:\n{done.stdout}\n{done.stderr}")
    return out.read_text(encoding="utf-8")


def to_html(markdown: str, folder: Path, work: Path) -> str:
    diagrams: list[str] = []

    def keep(match: re.Match) -> str:
        diagrams.append(match.group(1))
        return f"\n\nDIAGRAM-{len(diagrams) - 1}-HERE\n\n"

    text = re.sub(r"```mermaid\n(.*?)```", keep, markdown, flags=re.S)
    html = MarkdownIt("commonmark", {"html": True}).enable("table").render(text)
    for number, source in enumerate(diagrams):
        html = html.replace(f"<p>DIAGRAM-{number}-HERE</p>", f'<div class="figure">{draw(source, work, number)}</div>')

    def inline(match: re.Match) -> str:
        path = folder / match.group(1)
        kind = mimetypes.guess_type(path.name)[0] or "image/png"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        shot = " shot" if path.suffix.lower() in (".png", ".jpg", ".jpeg") else ""
        return f'<div class="figure{shot}"><img alt="{match.group(2)}" src="data:{kind};base64,{data}"></div>'

    html = re.sub(r'<p><img src="([^"]+)" alt="([^"]*)"\s*/?></p>', inline, html)
    # The status line under the title stands out, so nobody mistakes a draft for the final report.
    html = re.sub(r"<p>(<strong>Status:.*?)</p>", r'<div class="status">\1</div>', html, count=1, flags=re.S)
    # Links to other files of the repository mean nothing in a PDF that is sent on its own.
    html = re.sub(r'<a href="(?!https?:)[^"]*">(.*?)</a>', r"\1", html, flags=re.S)
    title = re.search(r"<h1>(.*?)</h1>", html, flags=re.S)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title.group(1) if title else "Report"}'
            f"</title><style>{CSS}</style></head><body>{html}</body></html>")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path, help="the stint report's Markdown file")
    parser.add_argument("--keep-html", action="store_true", help="also write the laid-out page beside the PDF")
    args = parser.parse_args()
    source = args.report.resolve()
    target = source.with_suffix(".pdf")
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        page = work / "report.html"
        page.write_text(to_html(source.read_text(encoding="utf-8"), source.parent, work), encoding="utf-8")
        if args.keep_html:
            shutil.copy(page, source.with_suffix(".html"))
        subprocess.run([browser(), "--headless=new", "--disable-gpu", f"--user-data-dir={work / 'profile'}",
                        "--no-pdf-header-footer", f"--print-to-pdf={target}", page.as_uri()],
                       capture_output=True, text=True, timeout=180)
    if not target.is_file():
        raise SystemExit("The browser did not write the PDF.")
    print(f"wrote {target} ({target.stat().st_size // 1024} kB)")


if __name__ == "__main__":
    sys.exit(main())
