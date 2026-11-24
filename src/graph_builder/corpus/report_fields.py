"""Recover missing report fields from typed values on the same visible PDF row."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

from .daily_header import glyph_line
from .table_recognition import page_lines
from .text_layer import source_page, union

DATE = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}-[a-z]{3}-\d{2,4})"
CLOCK = r"\d{1,2}:\d{2}"
NUMBER = r"[+-]?\d[\d,]*(?:\.\d+)?"
AMOUNT = r"\$\d+(?:,\d{3})*(?:\.\d{2})?"
DEPTH = fr"{NUMBER}(?:\s*/\s*{NUMBER})?\s*(?:ft|m)(?:\s*\(TD\))?"
BODY = re.compile(r"^(?:from\s+to\b|operations summary\b|ops summary\b|daily op['’]s\b|forecast op['’]s\b)", re.I)
DAILY_TITLE = re.compile(r"\bdaily\s+(?:drilling|well)\s+(?:report|summary)\b", re.I)
WEATHER_TITLE = re.compile(r"^(?:weather information|weather conditions|weather)$", re.I)
IDENTIFIERS = {"well", "report", "date", "report_for", "period", "permit", "spud"}
REPORT_ID = {"well", "report", "period"}

# Named groups delimit the printed label and its value without retyping either. Strong delimiters and value
# grammars let this work on ordinary, ruled and whitespace-aligned headers from the same PDF text layer.
RULES = {
    "well": r"^(?P<key>well(?:bore|\s+(?:id|name))?\s*:?)\s+"
            r"(?P<value>[a-z0-9][a-z0-9.()/\[\] -]*?)"
            r"(?=\s+(?:well\s+(?:name|id)\b|date\s*:|date\s+\d|field\s*:|"
            r"job\s*:|permit\s*:|\d{1,2}:\d{2}\s+md|report\s+(?:no\b|#|for\b|date\b)|period\s*:)|$)",
    "report": fr"(?<!\w)(?P<key>(?:report|rpt)\s*(?:\#|number\b|no\b\.?|num\b\.?)(?:\s*:)?)(?:\s+)"
              fr"(?P<value>\d+(?:\s+{DATE})?)(?=\s|$)",
    "date": fr"(?<!\w)(?<!spud\s)(?P<key>(?:report\s+)?date\s*:?)\s+(?P<value>{DATE})(?=\s|$)",
    "report_for": fr"(?<!\w)(?P<key>report\s+for\s*:?)\s+(?P<value>{DATE})(?=\s|$)",
    "period": fr"(?<!\w)(?P<key>period\s*:)\s+(?P<value>{DATE}\s+{CLOCK}\s+[-–]\s+{DATE}\s+{CLOCK})(?=\s|$)",
    "permit": r"(?<!\w)(?P<key>permit(?:\s+(?:no\.?|number))?\s*:)\s+"
              r"(?P<value>(?:[a-z]+\s+)?[a-z0-9-]*\d[a-z0-9/-]*)(?=\s|$)",
    "spud": fr"(?<!\w)(?P<key>spud(?:\s+date)?\s*:?)\s+(?P<value>{DATE})(?=\s|$)",
    "measured_depth": fr"(?<!\w)(?P<key>{CLOCK}\s+md\s*/\s*tvd\s*:?)\s+(?P<value>{DEPTH})(?=\s|$)",
    "daily_cost": fr"(?<![a-z])(?P<key>daily\s+cost\s*:?)\s+(?P<value>{AMOUNT})(?=\s|$|cum\.)",
    "cumulative_cost": fr"(?<![a-z])(?P<key>cum\.(?:\s+cost)?\s*:?)\s+(?P<value>{AMOUNT})(?=\s|$)",
}
WEATHER = {
    "air_temperature": fr"(?<!\w)(?P<key>air\s+temperature\s*:)\s+(?P<value>{NUMBER}\s+(?:deg[fc]|°\s*[fc]))(?=\s|$)",
    "pressure": fr"(?<!\w)(?P<key>bar\.\s+pressure\s*:)\s+(?P<value>{NUMBER})(?=\s|$)",
    "wind_gusts": fr"(?<!\w)(?P<key>wind\s+gusts\s*:)\s+(?P<value>{NUMBER})(?=\s|$)",
    "wind": fr"(?<!\w)(?P<key>wind\s+speed\s*/\s*dir\s*:)\s+(?P<value>{NUMBER}\s*/\s*[nsew]{{1,3}})(?=\s|$)",
    "sky": r"(?<!\w)(?P<key>sky\s+condition\s*:)\s+(?P<value>partly cloudy|clear|overcast|cloudy)(?=\s|$)",
}
HEADER_RULES = {kind: re.compile(pattern, re.I) for kind, pattern in RULES.items()}
WEATHER_RULES = {kind: re.compile(pattern, re.I) for kind, pattern in WEATHER.items()}


def normalized(text: str) -> str:
    return " ".join(text.replace("|", " ").split()).casefold()


def observed(field: dict, body: str) -> bool:
    key = normalized(field["key"])
    value = normalized(field["value"])
    return bool(re.search(rf"(?<!\w){re.escape(key.rstrip(':'))}\s*:?\s+{re.escape(value)}(?![\w/-]|[.,]\d)", body))


def field_candidates(layer, rows, rules):
    for row, text in rows:
        matches = [(kind, m) for kind, rule in rules.items() for m in rule.finditer(text)]
        if not matches:
            continue
        glyphs = glyph_line(layer, row["words"])
        if not glyphs:
            continue
        for kind, match in matches:
            key, value = (match.group(group).strip() for group in ("key", "value"))
            if kind == "well" and (len(value.split()) > 8 or not any(char.isdigit() for char in value)):
                continue
            key_box, value_box = (union([b for b in glyphs[slice(*match.span(group))] if b])
                                  for group in ("key", "value"))
            if not -0.5 <= value_box[0] - key_box[2] <= layer["width"] / 5:
                continue
            yield kind, {
                "key": key, "value": value, "key_bbox": key_box, "value_bbox": value_box,
                "canonical_key": "report_reference" if kind == "report" and " " in value else kind,
                "verified": False, "source_word_boxes": True,
            }


def aligned_pair(field: dict, other: dict, em: float) -> bool:
    key, value = field["key_bbox"], field["value_bbox"]
    peer_key, peer_value = other["key_bbox"], other["value_bbox"]
    dy = abs(key[1] - peer_key[1])
    return (em / 2 <= dy <= 4 * em and abs(key[0] - peer_key[0]) <= 3 * em
            and abs((value[0] + value[2]) - (peer_value[0] + peer_value[2])) <= 6 * em)


def supported(field: dict, peers: list[dict]) -> bool:
    key, value = field["key_bbox"], field["value_bbox"]
    em = key[3] - key[1]
    # A long horizontal gap needs another typed field on a neighboring row with the same column alignment.
    return value[0] - key[2] <= max(18, 8 * em) or any(aligned_pair(field, peer, em) for peer in peers)


def source_fields(layer: dict, require_signature: bool = False) -> tuple[float, list[dict]]:
    boundary = layer["height"] / 3
    if layer["rotation"]:
        return boundary, []
    rows = [(row, " ".join(word["text"] for word in row["words"])) for row in page_lines(layer)]
    header = []
    for row, text in rows:
        if row["bottom"] > boundary or BODY.search(text):
            break
        header.append((row, text))
    candidates = list(field_candidates(layer, header, HEADER_RULES))
    peers = [field for _, field in candidates]
    candidates = [(kind, field) for kind, field in candidates if supported(field, peers)]
    kinds = {kind for kind, _ in candidates} & IDENTIFIERS
    if len(kinds) < 2:
        return boundary, []
    if require_signature:
        dated_identity = {"well", "report"} <= kinds and kinds & {"date", "report_for", "period"}
        if not dated_identity and not any(DAILY_TITLE.search(text) for _, text in header):
            return boundary, []
    for kind in REPORT_ID:
        values = {normalized(field["value"]) for field_kind, field in candidates if field_kind == kind}
        if len(values) > 1:
            return boundary, []
    weather = [idx for idx, (_, text) in enumerate(rows) if WEATHER_TITLE.fullmatch(text)]
    if len(weather) == 1:
        nearby = rows[weather[0] + 1:weather[0] + 6]
        weather_fields = list(field_candidates(layer, nearby, WEATHER_RULES))
        peers = [field for _, field in weather_fields]
        candidates.extend((kind, field) for kind, field in weather_fields if supported(field, peers))
        if nearby:
            boundary = max(boundary, nearby[-1][0]["bottom"])
    groups = defaultdict(dict)
    for kind, field in candidates:
        groups[(kind, normalized(field["key"]).rstrip(":"))].setdefault(normalized(field["value"]), field)
    return boundary, [next(iter(values.values())) for values in groups.values() if len(values) == 1]


def source_report_identity(layer: dict) -> dict[str, tuple[str, ...]]:
    """Resolve printed report identity for comparing pages of a possible table continuation."""
    from datetime import datetime

    if layer.get("normalized"):
        layer = dict(layer, rotation=0)
    _, fields = source_fields(layer, require_signature=True)

    def date_candidates(value):
        dates = set()
        for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%d-%b-%y"):
            try:
                dates.add(datetime.strptime(value, pattern).date().isoformat())
            except ValueError:
                continue
        return tuple(sorted(dates))

    identity = defaultdict(set)
    for field in fields:
        key, value = field["canonical_key"], field["value"]
        if key in ("report", "report_reference"):
            number, _, date = value.partition(" ")
            identity["report_number"].add((number.lstrip("0") or "0",))
            if date and (parsed := date_candidates(date)):
                identity["report_reference_date"].add(parsed)
        elif key == "report_for" or (key == "date" and normalized(field["key"]).startswith("report ")):
            if parsed := date_candidates(value):
                identity["report_for" if key == "report_for" else "printed_report_date"].add(parsed)
        elif key in {"well", "period"}:
            identity[key].add((normalized(value),))
    return {key: next(iter(values)) for key, values in identity.items() if len(values) == 1}


def recover_fields(pdf: Path, pages: list[dict], forms: list[dict], text: dict[int, str], minimum_share: float,
                   stacked_pages=(), *, require_signature: bool = False) -> list[dict]:
    """Append missing physical pairs to existing form records, preserving existing form indices."""
    by_page = defaultdict(list)
    for form in forms:
        by_page[form["page"]].append(form)
    result = list(forms)
    for entry in pages:
        page = entry["page"]
        originals = by_page[page]
        if entry.get("mode") != "text" or page in stacked_pages or len(originals) > 1:
            continue
        layer = source_page(pdf, page, displayed_origin=True)
        boundary, fields = source_fields(layer, require_signature)
        body = normalized(text.get(page, ""))
        prior = originals[0] if originals else None
        keys = {normalized(f["key"]).rstrip(":") for f in prior["fields"]} if prior else set()
        fields = [f for f in fields if normalized(f["key"]).rstrip(":") not in keys and not observed(f, body)]
        if not fields:
            continue
        if prior:
            result[result.index(prior)] = dict(prior, fields=prior["fields"] + fields,
                                               header_boundary=max(prior["header_boundary"], boundary))
        else:
            result.append({
                "page": page, "status": "success", "fields": fields, "reference_text": layer["text"],
                "header_boundary": boundary, "bbox_frame": "displayed physical page, top-left PDF points",
                "rotation": layer["rotation"], "text_layer_only": True, "visible_glyph_clipping": True,
                "method": "generic", "verified": False, "template_label_share": 0.0,
                "template_minimum_share": minimum_share,
            })
    return result
