"""Draw the stint report's diagrams as SVG files in docs/reports/stints/figures/.

    python scripts/stint_figures.py

Plain SVG with real text (no scripts, no outside fonts), so the files show on GitHub, in the PDF and on a slide.
Edit the text here and run again; the figures are generated, not drawn by hand. Standard library only.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs/reports/stints/figures"
FONT = "Segoe UI, Arial, Helvetica, sans-serif"
INK, TEXT, MUTED, LINE, PAGE = "#0f1e33", "#33445c", "#5d6d85", "#c9d4e3", "#f5f8fc"
BLUE, BLUE_SOFT = "#1d5fd6", "#e6effe"
GREEN, GREEN_SOFT = "#14734a", "#dcf5e8"
AMBER, AMBER_SOFT = "#a45a06", "#fff1da"
TEAL, TEAL_SOFT = "#0e7c86", "#dff3f4"
VIOLET, VIOLET_SOFT = "#6b46c1", "#eee9fb"
GREY_SOFT = "#eef3fa"


class Svg:
    def __init__(self, width: int, height: int, title: str):
        self.width, self.height, self.title, self.parts = width, height, title, []

    def add(self, text: str) -> None:
        self.parts.append(text)

    def rect(self, x, y, w, h, fill="#fff", stroke=LINE, radius=10, width=1.5, dash=None) -> None:
        dashed = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="{width}"{dashed}/>')

    def text(self, x, y, value, size: float = 14, weight=400, fill=TEXT, anchor="middle") -> None:
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
                 f'text-anchor="{anchor}">{escape(value)}</text>')

    def box(self, x, y, w, h, title, lines=(), fill="#fff", stroke=LINE, title_fill=INK, size: float = 14) -> None:
        """A box with a bold title and smaller lines under it, centred as a block."""
        self.rect(x, y, w, h, fill, stroke)
        step = size + 4
        top = y + h / 2 - (len(lines) * step) / 2 + size * 0.35
        self.text(x + w / 2, top, title, size, 700, title_fill)
        for n, line in enumerate(lines, 1):
            self.text(x + w / 2, top + n * step, line, size - 2, 400, TEXT)

    def panel(self, x, y, w, h, number, title, owner, colour, soft) -> None:
        """A titled group: a coloured header with a number, a name and its owner."""
        self.rect(x, y, w, h, soft, colour, 14, 2)
        self.add(f'<path d="M{x},{y + 40} v-26 a14,14 0 0 1 14,-14 h{w - 28} a14,14 0 0 1 14,14 v26 z" fill="{colour}"/>')
        self.add(f'<circle cx="{x + 24}" cy="{y + 20}" r="12" fill="#fff"/>')
        self.text(x + 24, y + 25, str(number), 14, 800, colour)
        self.text(x + 44, y + 26, title, 15, 700, "#fff", "start")
        self.text(x + w - 14, y + 26, owner, 14, 600, "#fff", "end")

    def arrow(self, points, label=None, dashed=False, colour=MUTED, label_at=None) -> None:
        path = "M" + " L".join(f"{x},{y}" for x, y in points)
        dash = ' stroke-dasharray="7 6"' if dashed else ""
        self.add(f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="2.2"{dash} marker-end="url(#head-{colour[1:]})"/>')
        self.heads.add(colour)
        if label:
            (x1, y1), (x2, y2) = points[0], points[1]
            lx, ly = label_at or ((x1 + x2) / 2, (y1 + y2) / 2 - 8)
            width = len(label) * 6.6 + 14
            self.add(f'<rect x="{lx - width / 2}" y="{ly - 13}" width="{width}" height="19" rx="9" fill="#fff" stroke="{colour}" stroke-width="1"/>')
            self.text(lx, ly + 1, label, 11.5, 600, colour)

    heads: set

    def save(self, name: str) -> None:
        heads = "".join(
            f'<marker id="head-{c[1:]}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>' for c in sorted(self.heads))
        body = "\n".join(self.parts)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" width="{self.width}" '
               f'height="{self.height}" font-family="{FONT}" role="img" aria-label="{escape(self.title)}">\n'
               f'<title>{escape(self.title)}</title>\n<defs>{heads}</defs>\n'
               f'<rect width="{self.width}" height="{self.height}" fill="#ffffff"/>\n{body}\n</svg>\n')
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / name).write_text(svg, encoding="utf-8", newline="\n")
        print(f"wrote {name}")


def new(width: int, height: int, title: str) -> Svg:
    svg = Svg(width, height, title)
    svg.heads = set()
    return svg


def legend(svg: Svg, x: int, y: int, items: list[tuple[str, str, str]]) -> None:
    for fill, stroke, label in items:
        svg.rect(x, y - 12, 18, 14, fill, stroke, 4)
        svg.text(x + 26, y, label, 12.5, 400, TEXT, "start")
        x += 40 + len(label) * 6.9


def architecture() -> None:
    s = new(1240, 690, "The four parts of the system and who owns each")
    # The source documents
    s.box(20, 170, 140, 96, "Drilling reports", ["PDF files:", "end-of-well and daily"], "#fff", MUTED)

    # 1. Reading the reports
    s.panel(190, 30, 250, 380, 1, "Reading the reports", "Khai", TEAL, TEAL_SOFT)
    steps = [("Read each page", ["text, tables and forms"]),
             ("Rebuild known tables", ["from the PDF's own text"]),
             ("Cut into passages", ["each linked to page, well, date"]),
             ("Check against the PDF", ["nothing lost, nothing invented"])]
    for n, (title, lines) in enumerate(steps):
        s.box(208, 88 + n * 78, 214, 62, title, lines, "#fff", TEAL)
        if n:
            s.arrow([(315, 88 + n * 78 - 16), (315, 88 + n * 78 - 2)], colour=TEAL)

    # 3. Answering engine
    s.panel(480, 30, 430, 380, 3, "Answering engine", "Tri", BLUE, BLUE_SOFT)
    s.box(500, 86, 390, 74, "Coordinator", ["understands the question (one AI call)", "code chooses where to look"], "#fff", BLUE)
    places = [("Report text", "search"), ("Well facts", "checked values"), ("Activities", "totals by day"), ("Causes", "around a problem")]
    for n, (title, sub) in enumerate(places):
        s.box(500 + n * 99, 196, 93, 66, title, [sub], "#fff", BLUE, size=12.5)
        s.arrow([(546 + n * 99, 160), (546 + n * 99, 194)], colour=BLUE)
        s.arrow([(546 + n * 99, 262), (546 + n * 99, 300)], colour=BLUE)
    s.box(500, 302, 390, 86, "The answer", ["a total: calculated by code", "otherwise: written by AI (one call),", "then checked against the text by code"], "#fff", BLUE)

    # 4. Application
    s.panel(950, 30, 270, 380, 4, "Application", "Tri and Hung", VIOLET, VIOLET_SOFT)
    s.box(968, 86, 234, 74, "Backend service", ["ask a question, open a source,", "mark an answer right or wrong"], "#fff", VIOLET)
    s.arrow([(1085, 160), (1085, 194)], colour=VIOLET)
    s.box(968, 196, 234, 92, "Web application", ["for people who are not developers:", "answer, trust label, evidence,", "a guide, explanations on hover"], "#fff", VIOLET)
    s.arrow([(1085, 288), (1085, 316)], colour=VIOLET)
    s.box(968, 318, 234, 70, "Question log", ["every question and its answer,", "and every right or wrong mark"], "#fff", VIOLET)

    # 2. Stores
    s.panel(190, 480, 1030, 150, 2, "Stores", "Hung", GREEN, GREEN_SOFT)
    stores = [("PostgreSQL", ["passages, pages, search vectors,", "the question log"]),
              ("Neo4j", ["the knowledge graph:", "facts and activities"]),
              ("File store", ["a folder: report packages", "and page images"]),
              ("Loader", ["one command loads a package", "and checks every step"])]
    for n, (title, lines) in enumerate(stores):
        s.box(208 + n * 252, 536, 238, 76, title, lines, "#fff", GREEN)

    # Connections
    s.arrow([(160, 218), (188, 218)])
    s.arrow([(440, 150), (478, 150)])
    s.add(f'<text transform="translate(464,300) rotate(-90)" font-size="12" font-weight="600" fill="{MUTED}" text-anchor="middle">passages, as files too</text>')
    s.arrow([(910, 123), (948, 123)])
    s.add(f'<text transform="translate(934,300) rotate(-90)" font-size="12" font-weight="600" fill="{MUTED}" text-anchor="middle">answers with their evidence</text>')
    s.arrow([(315, 410), (315, 478)], "passage packages", colour=GREEN, label_at=(315, 446))
    s.arrow([(695, 478), (695, 412)], "passages, activities, facts", colour=GREEN, label_at=(695, 446))
    s.arrow([(1085, 410), (1085, 478)], "the question log", colour=GREEN, label_at=(1085, 446))

    s.add(f'<path d="M208,664 h44" stroke="{MUTED}" stroke-width="2.2"/>')
    s.text(260, 668, "works today", 12.5, 400, TEXT, "start")
    s.text(368, 668, "All four parts run together on one machine. A shared server is the next step.", 12.5, 400, TEXT, "start")
    s.save("architecture.svg")


def question_flow() -> None:
    s = new(1240, 750, "How a question is answered, step by step")
    columns = [(20, 150, "Ask"), (200, 250, "Understand"), (490, 300, "Look in the right place"), (830, 390, "Answer and check")]
    for n, (x, w, title) in enumerate(columns, 1):
        s.add(f'<circle cx="{x + 16}" cy="34" r="15" fill="{INK}"/>')
        s.text(x + 16, 39, str(n), 15, 800, "#fff")
        s.text(x + 40, 40, title, 17, 700, INK, "start")

    # 1. Ask
    s.box(20, 208, 150, 110, "A person asks", ["in plain English"], "#fff", MUTED)
    s.arrow([(170, 263), (198, 263)])

    # 2. Understand
    s.box(200, 150, 250, 132, "One AI call", ["What kind of question is it?", "Which reports is it about?", "For a total: a small plan,", "such as \"total hours, August\""], BLUE_SOFT, BLUE)
    s.box(200, 298, 250, 84, "Code", ["reads the well name and the dates,", "and chooses where to look", "from a fixed table"], GREEN_SOFT, GREEN)
    s.add(f'<path d="M450,216 H472 M450,340 H472 M472,109 V409" fill="none" stroke="{MUTED}" stroke-width="2.2"/>')

    # 3. Look: four places, one arrow into each
    places = [(70, "Daily activities", ["for totals over a period:", "hours, days, counts, depth"], AMBER, AMBER_SOFT),
              (170, "Around one problem", ["for questions about causes:", "its activities and report text"], BLUE, "#fff"),
              (270, "Well facts", ["checked values:", "depths, dates, casing"], BLUE, "#fff"),
              (370, "Report text", ["search the passages", "of that well and date"], BLUE, "#fff")]
    for y, title, lines, stroke, fill in places:
        s.box(490, y, 300, 78, title, lines, fill, stroke)
        s.arrow([(472, y + 39), (488, y + 39)])
    s.arrow([(640, 496), (640, 452)], dashed=True, colour=AMBER)
    s.rect(497, 498, 286, 22, "#fff", AMBER, 11, 1)
    s.text(640, 513, "nothing found there: the report text is searched", 11.5, 600, AMBER)

    # 4. Answer and check
    s.box(830, 70, 390, 78, "Code calculates the total", ["adds up the matching activities;", "no AI writes the number"], GREEN_SOFT, GREEN)
    s.arrow([(790, 109), (828, 109)], colour=AMBER)
    s.box(830, 214, 390, 90, "One AI call writes the answer", ["only from the facts and the text", "it was given"], BLUE_SOFT, BLUE)
    s.arrow([(790, 209), (808, 209), (808, 244), (828, 244)])
    s.arrow([(790, 309), (808, 309), (808, 274), (828, 274)])
    s.add(f'<path d="M790,409 H808 V309" fill="none" stroke="{MUTED}" stroke-width="2.2"/>')
    s.box(830, 370, 390, 78, "Code checks the answer", ["Is the value really written", "in the text that was read?"], GREEN_SOFT, GREEN)
    s.arrow([(1025, 304), (1025, 368)])

    # Results
    s.rect(20, 566, 1200, 132, PAGE, LINE, 14)
    s.text(40, 592, "What the person sees", 15, 700, INK, "start")
    results = [(40, "Calculated from the reports", "with the activities it was added up from", GREEN, GREEN_SOFT),
               (432, "Written by AI, checked against the reports", "with the passage it comes from, highlighted", BLUE, BLUE_SOFT),
               (824, "No answer found", "the closest report text is shown instead", MUTED, GREY_SOFT)]
    for x, title, sub, stroke, fill in results:
        s.box(x, 606, 376, 74, title, [sub], fill, stroke, stroke if stroke != MUTED else INK)
    s.add(f'<path d="M1220,109 H1232 V550 H228 V604" fill="none" stroke="{GREEN}" stroke-width="2.2" marker-end="url(#head-{GREEN[1:]})"/>')
    s.heads.add(GREEN)
    s.add(f'<path d="M940,448 V534 H620 V604" fill="none" stroke="{BLUE}" stroke-width="2.2" marker-end="url(#head-{BLUE[1:]})"/>')
    s.heads.add(BLUE)
    s.text(930, 480, "yes", 12, 700, BLUE, "end")
    s.add(f'<path d="M1100,448 V604" fill="none" stroke="{MUTED}" stroke-width="2.2" marker-end="url(#head-{MUTED[1:]})"/>')
    s.text(1108, 480, "no, or not found", 12, 700, MUTED, "start")

    legend(s, 20, 730, [(BLUE_SOFT, BLUE, "uses the AI model"), (GREEN_SOFT, GREEN, "plain code, no AI"), (AMBER_SOFT, AMBER, "the daily activities, where totals come from")])
    s.save("question-flow.svg")


def graph() -> None:
    s = new(1240, 580, "The knowledge graph: one graph, two regions, joined at the well")
    # Regions
    s.rect(330, 24, 590, 232, AMBER_SOFT, AMBER, 14, 1.5, "6 5")
    s.text(350, 50, "Activities, from the daily reports (built by code, no AI)", 14, 700, AMBER, "start")
    s.rect(330, 304, 590, 232, BLUE_SOFT, BLUE, 14, 1.5, "6 5")
    s.text(350, 522, "Facts, from the end-of-well reports (by table rules and AI, then checked)", 14, 700, BLUE, "start")

    # The well
    s.add(f'<circle cx="150" cy="280" r="74" fill="{INK}"/>')
    s.text(150, 276, "Well", 22, 800, "#fff")
    s.text(150, 300, "for example AK-3", 13, 400, "#dbe6f5")

    # Activities
    s.box(360, 100, 150, 84, "Day", ["one per report day"], "#fff", AMBER)
    s.box(560, 84, 170, 116, "Activity", ["from, to, hours,", "depth reached,", "what happened"], "#fff", AMBER)
    s.box(770, 74, 130, 58, "Activity code", [], "#fff", AMBER, size=13)
    s.box(770, 150, 130, 74, "Non-productive", ["code, if marked"], "#fff", AMBER, size=13)
    s.arrow([(510, 142), (558, 142)], "has", colour=AMBER, label_at=(534, 124))
    s.arrow([(730, 120), (768, 104)], colour=AMBER)
    s.arrow([(730, 164), (768, 184)], colour=AMBER)

    # Facts
    s.box(360, 352, 250, 116, "Fact", ["what it is, its value and unit,", "planned or actual,", "what it applies to"], "#fff", BLUE)
    s.box(660, 372, 230, 76, "Casing and hole sections", ["size, depth, weight, grade"], "#fff", BLUE)

    # Sources
    s.box(990, 106, 220, 84, "Report", ["one PDF file"], GREEN_SOFT, GREEN)
    s.box(990, 250, 220, 96, "Passage", ["a piece of a page;", "its text and page stay", "in PostgreSQL"], GREEN_SOFT, GREEN)
    s.arrow([(1100, 190), (1100, 248)], "contains", colour=GREEN, label_at=(1100, 219))

    # From the well
    s.arrow([(206, 232), (300, 142), (358, 142)], "has day", colour=AMBER, label_at=(268, 150))
    s.arrow([(206, 328), (300, 410), (358, 410)], "has fact", colour=BLUE, label_at=(268, 388))
    s.add(f'<path d="M170,352 V556 H936 V410 H892" fill="none" stroke="{BLUE}" stroke-width="2.2" marker-end="url(#head-{BLUE[1:]})"/>')
    s.text(250, 572, "has casing, has section", 11.5, 600, BLUE, "start")
    s.add(f'<path d="M150,206 V12 H1100 V104" fill="none" stroke="{GREEN}" stroke-width="2.2" marker-end="url(#head-{GREEN[1:]})"/>')
    s.heads.add(GREEN)
    s.text(160, 30, "described by", 11.5, 600, GREEN, "start")

    # Read from
    s.add(f'<path d="M645,200 V238 H950 V280 H988" fill="none" stroke="{GREEN}" stroke-width="2.2" marker-end="url(#head-{GREEN[1:]})"/>')
    s.add(f'<path d="M485,352 V324 H950 V310 H988" fill="none" stroke="{GREEN}" stroke-width="2.2" marker-end="url(#head-{GREEN[1:]})"/>')
    s.text(940, 274, "read from", 11.5, 600, GREEN, "end")
    s.save("knowledge-graph.svg")


def deployment() -> None:
    s = new(1240, 470, "How the application runs: containers behind one password")
    s.box(20, 150, 150, 90, "A person", ["a browser,", "laptop or phone"], "#fff", MUTED)
    s.rect(200, 30, 800, 400, PAGE, LINE, 14, 2, dash="8 6")
    s.text(216, 56, "One machine, started with one command (containers)", 14, 700, INK, "start")
    s.box(222, 150, 190, 90, "Proxy", ["HTTPS, one shared password,", "serves the web application"], VIOLET_SOFT, VIOLET)
    s.box(452, 130, 220, 130, "Backend service", ["one question at a time,", "the others wait their turn;", "every question is logged,", "failures told in plain words"], VIOLET_SOFT, VIOLET)
    s.box(452, 300, 220, 96, "Answering engine", ["the coordinator and its", "four places to look", "(runs inside the service)"], BLUE_SOFT, BLUE)
    s.box(712, 80, 268, 76, "PostgreSQL", ["passages, search vectors, pages,", "the question log"], GREEN_SOFT, GREEN)
    s.box(712, 176, 268, 76, "Neo4j", ["the knowledge graph:", "161 activities, 206 facts"], GREEN_SOFT, GREEN)
    s.box(712, 272, 268, 62, "Report package", ["a folder: page images"], GREEN_SOFT, GREEN)
    s.box(712, 346, 268, 54, "Monitor and nightly backup", ["alert to the group chat; copy kept elsewhere"], "#fff", MUTED, size=13)
    s.box(1030, 130, 190, 130, "AI model", ["Qwen3-8B, the team's", "own copy (llama.cpp),", "or a hosted open model", "for public data only"], AMBER_SOFT, AMBER)
    s.arrow([(170, 195), (220, 195)])
    s.arrow([(412, 195), (450, 195)], colour=VIOLET)
    s.arrow([(562, 260), (562, 298)], colour=BLUE)
    s.arrow([(672, 150), (710, 122)], colour=GREEN)
    s.arrow([(672, 200), (710, 212)], colour=GREEN)
    s.arrow([(672, 240), (710, 296)], colour=GREEN)
    s.arrow([(562, 396), (562, 418), (1125, 418), (1125, 262)], "at most two calls a question", colour=AMBER, label_at=(1125, 340))
    legend(s, 222, 452, [(VIOLET_SOFT, VIOLET, "application"), (BLUE_SOFT, BLUE, "engine"), (GREEN_SOFT, GREEN, "stores"), (AMBER_SOFT, AMBER, "AI model")])
    s.save("deployment.svg")


def expert_path() -> None:
    s = new(1240, 300, "From an expert's input to a test")
    steps = [("1. Ask and mark", ["the expert uses the", "application: Yes or No,", "and the right answer"], VIOLET_SOFT, VIOLET),
             ("2. Question log", ["every question, the", "answer given, the mark"], GREEN_SOFT, GREEN),
             ("3. Spreadsheet", ["one command; answers", "marked right are", "already filled in"], "#fff", MUTED),
             ("4. Expert fills", ["the expected answer in", "plain words: 1955 ft,", "not stated"], VIOLET_SOFT, VIOLET),
             ("5. Test file", ["one command; it records", "who wrote the answers"], "#fff", MUTED),
             ("6. Run", ["the system answers", "every question, by hand-", "chosen place and by", "the coordinator"], BLUE_SOFT, BLUE)]
    width, gap, left = 178, 26, 20
    for n, (title, lines, fill, stroke) in enumerate(steps):
        x = left + n * (width + gap)
        s.box(x, 60, width, 130, title, lines, fill, stroke, size=13.5)
        if n:
            s.arrow([(x - gap + 2, 125), (x - 2, 125)])
    s.arrow([(left + 3 * (width + gap) + width / 2, 232), (left + 3 * (width + gap) + width / 2, 192)], colour=VIOLET)
    s.text(left + 3 * (width + gap) + width / 2, 250, "or start here, with an empty sheet", 12.5, 600, VIOLET)
    s.text(620, 32, "No step needs programming, and no AI is used until step 6", 14, 700, INK)
    legend(s, 20, 284, [(VIOLET_SOFT, VIOLET, "done by the expert"), ("#fff", MUTED, "one command by the team"), (BLUE_SOFT, BLUE, "the measurement")])
    s.save("expert-path.svg")


if __name__ == "__main__":
    architecture()
    question_flow()
    graph()
    deployment()
    expert_path()
