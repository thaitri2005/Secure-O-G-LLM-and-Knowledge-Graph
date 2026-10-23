"""Map emitted characters to source items and physical pages without changing text."""
from difflib import SequenceMatcher
import re


def source_spans(document, text, items):
    """Align serializer tokens with item text and provenance character spans.

    Formatting characters inherit the nearest matched token's source. Unmatched
    output tokens are retained too, so serialization additions still hurt precision.
    """
    source = []
    for item, selected_page in items:
        item = item.get_ref().resolve(document)
        raw = getattr(item, "text", None)
        if raw is None:
            raw = " ".join(cell.text for cell in getattr(getattr(item, "data", None), "table_cells", []))
        for prov in item.prov:
            if selected_page is not None and selected_page != prov.page_no:
                continue
            start, end = prov.charspan
            if raw and not hasattr(item, "text") and len(item.prov) > 1 and end > start:
                page_raw = " ".join(cell.text for cell in item.data.table_cells
                                    if start <= cell.start_row_offset_idx < end)
                for match in re.finditer(r"\w+|[^\w\s]", page_raw):
                    source.append((match.group(), item.self_ref, prov.page_no, match.start(), match.end()))
                continue
            if len(item.prov) == 1 or not getattr(item, "text", None):
                start, end = 0, len(raw)
            for match in re.finditer(r"\w+|[^\w\s]", raw[start:end]):
                source.append((match.group(), item.self_ref, prov.page_no,
                               start + match.start(), start + match.end()))
    target = list(re.finditer(r"\w+|[^\w\s]", text))
    if not source and items and text:
        item, page = items[0]
        return [{"source_ref": item.self_ref, "page": page or item.prov[0].page_no,
                 "start": 0, "end": len(text), "source_start": 0, "source_end": 0}]
    if not target or not source:
        return []
    owners = {}
    matcher = SequenceMatcher(None, [s[0] for s in source], [m.group() for m in target], autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            owners[block.b + offset] = source[block.a + offset]
    if not owners:
        owners[0] = source[0]
    matched = sorted(owners)
    nearest = 0
    result = []
    for index, match in enumerate(target):
        while nearest + 1 < len(matched) and abs(matched[nearest + 1] - index) < abs(matched[nearest] - index):
            nearest += 1
        owner = owners.get(index, owners[matched[nearest]])
        end = target[index + 1].start() if index + 1 < len(target) else len(text)
        start = match.start() if index else 0
        if result and (result[-1]["source_ref"], result[-1]["page"]) == (owner[1], owner[2]):
            result[-1]["end"] = end
            result[-1]["source_end"] = max(result[-1]["source_end"], owner[4])
        else:
            result.append({"source_ref": owner[1], "page": owner[2], "start": start, "end": end,
                           "source_start": owner[3], "source_end": owner[4]})
    return result


def page_texts(record):
    """Return only the emitted character slices attributed to each source page."""
    pages = {}
    spans = record.get("source_spans")
    if spans is None:
        if len({r["page"] for r in record.get("regions", [])}) > 1:
            raise ValueError("Multi-page chunks require source character spans")
        return {record["page"]: record["text"]}
    for span in spans:
        pages.setdefault(span["page"], []).append(record["text"][span["start"]:span["end"]])
    return {page: "\n".join(pieces) for page, pieces in pages.items()}
