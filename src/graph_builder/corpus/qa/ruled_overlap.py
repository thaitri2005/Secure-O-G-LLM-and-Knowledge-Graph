"""Prefer independently corroborated cells in retrieval while retaining the K1 source records."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import re
import unicodedata

from ..numeric_cells import COMPOUND, RULE as NUMERIC_RULE, compact
from ..store import read_jsonl
from .cell_evidence import FRAME, ident, overlaps
from .crossrep import analyse_table, load_config
from .form_overlap import covers, valid_box
from .table_overlap import load_native, mask_cells, text_edits

CHECK = "ruled_table_overlap"
REASON = "RULED_TABLE_OVERLAP_PROJECTED"
PREFIXES = ("textlayer:mud_properties:", "textlayer:ruled_panels:", "textlayer:casing:")
COMPOUND_REASONS = {"native_box_spans_source_rows", "native_box_spans_source_columns"}
VALUE_TOKEN = re.compile(r"[+\-−]?\d+(?:[.,:]\d+)*|[^\W\d]\w*|[^\w\s]", re.UNICODE)


def value_tokens(text):
    """Retain signed and decimal values as units when comparing reordered source text."""
    return VALUE_TOKEN.findall(unicodedata.normalize("NFC", text))


@dataclass(frozen=True)
class RuledPanel:
    table_id: str
    box: list
    context: dict
    cells: list[dict]

    def source_cells(self, box, text, *, native_margin=False):
        """Return complete source cells in the same box whose tokens exactly account for the text."""
        wanted = Counter(value_tokens(text))
        if not wanted or not valid_box(box):
            return []
        inside = covers(self.box, box)
        if not inside and (not native_margin or not overlaps(self.box, box)):
            return []
        cells = [cell for cell in self.cells if overlaps(cell["bbox"], box)]
        if not cells or (not all(covers(box, cell["bbox"]) for cell in cells)
                         and not (inside and len(cells) == 1 and covers(cells[0]["bbox"], box))):
            return []
        actual = Counter(token for cell in cells for token in value_tokens(cell["text"]))
        return cells if actual == wanted else []

    def matches(self, box, text):
        return bool(self.source_cells(box, text))


def reference_panels(tables, chunks, evidence, config):
    by_page = defaultdict(list)
    for table_id, table in tables.items():
        part, = table["parts"]
        children = chunks[table_id]
        page = part["page"]
        if (not children or not valid_box(part["bbox"]) or children[0]["row_start"] != table["header_rows"]
                or any(child["pages"] != [page] or child["ocr"] or child["quality"] != "ok"
                       or child["context"] != children[0]["context"] for child in children)
                or analyse_table(table, children, config)):
            continue
        expected = {ident(cell): cell["text"] for cell in table["cells"] if cell["text"].strip()}
        rows = [row for row in evidence[table_id] if row["status"] == "source_supported" and row["page"] == page
                and row["bbox_frame"] == FRAME and valid_box(row["bbox"]) and covers(part["bbox"], row["bbox"])]
        if expected and len(rows) == len(expected) and {ident(row): row["text"] for row in rows} == expected:
            by_page[table["file_id"], page].append(RuledPanel(table_id, part["bbox"], children[0]["context"], rows))
    return by_page


def positions(cell):
    return {(r, c) for r in range(cell["r"], cell["r"] + cell["row_span"])
            for c in range(cell["c"], cell["c"] + cell["col_span"])}


def numeric_source_groups(panel, row):
    """Locate each literal of a suspected compound in adjacent, corroborated source cells."""
    text, visible = compact(row["text"]), compact(row["observed_text"])
    literals = text.split()
    if not COMPOUND.fullmatch(text) or literals.count(visible) != 1:
        return []
    cells = {(cell["r"], cell["c"]): cell for cell in panel.cells
             if not cell["is_header"] and cell["row_span"] == cell["col_span"] == 1}
    anchors = [slot for slot, cell in cells.items() if cell["text"] == visible and overlaps(cell["bbox"], row["bbox"])]
    if len(anchors) != 1:
        return []
    r, c = anchors[0]
    groups = []
    for start in range(1 - len(literals), 1):
        indices = range(start, start + len(literals))
        for slots in ([(r + offset, c) for offset in indices], [(r, c + offset) for offset in indices]):
            if all(slot in cells for slot in slots) and Counter(cells[slot]["text"] for slot in slots) == Counter(literals):
                groups.append(slots)
    return groups


def native_targets(table, evidence, panels, first_body_row, *, native_margin=True, numeric_conflicts=frozenset()):
    owners = Counter(slot for cell in table["cells"] for slot in positions(cell))
    targets = []
    for row in evidence:
        if (row["method"] != "docling_region" or row["bbox_frame"] != FRAME or row["is_header"]
                or row["r"] < first_body_row or row["status"] not in ("text_matches_region", "review")):
            continue
        slots = positions(row)
        if any(owners[slot] != 1 for slot in slots):
            continue
        if Counter(value_tokens(row["text"])) != Counter(value_tokens(row["observed_text"] or "")):
            if (row["r"], row["c"]) in numeric_conflicts and len(slots) == 1 and valid_box(row["bbox"]):
                groups = [(panel, cells) for panel in panels for cells in numeric_source_groups(panel, row)]
                if len(groups) == 1:
                    panel, cells = groups[0]
                    targets.append((slots, {"native_table_id": table["table_id"], "native_r": row["r"], "native_c": row["c"],
                                            "retained_table_id": panel.table_id, "source_cells": [list(slot) for slot in cells],
                                            "action": "remove_uncertain_numeric_duplicate"}))
            continue
        # The independently read native rectangle has precisely these tokens, even if its margin extends past the panel.
        matches = [(panel, cells) for panel in panels if (cells := panel.source_cells(row["bbox"], row["text"], native_margin=native_margin))]
        if len(matches) != 1:
            continue
        panel, cells = matches[0]
        row_or_col_conflict = (row["reason"] in COMPOUND_REASONS
                               and (len({c["r"] for c in cells}) > 1 or len({c["c"] for c in cells}) > 1))
        evidence_row = {"native_table_id": table["table_id"], "native_r": row["r"], "native_c": row["c"], "retained_table_id": panel.table_id,
                        "source_cells": [[cell["r"], cell["c"]] for cell in cells],
                        "action": "prefer_source_rows_and_columns" if row_or_col_conflict else "remove_duplicate"}
        if not covers(panel.box, row["bbox"]):
            evidence_row["native_box_extends_past_panel"] = True
        targets.append((slots, evidence_row))
    return targets


class RuledOverlap:
    def __init__(self, release, corpus, load_evidence, legacy=None, *, native_margin=True):
        self.findings = defaultdict(list)
        self.replacements = {}
        if corpus is None:
            return
        records = {row["table_id"]: row for row in read_jsonl(release / "tables.jsonl")}
        candidates = {tid: row for tid, row in records.items() if len(row["parts"]) == 1
                      and row["parts"][0]["source_ref"].startswith(PREFIXES)}
        if not candidates:
            return
        files = {table["file_id"] for table in candidates.values()}
        evidence = defaultdict(list)
        for row in load_evidence().rows:
            if row["file_id"] in files:
                evidence[row["table_id"]].append(row)
        table_chunks, file_chunks = defaultdict(list), defaultdict(list)
        for chunk in read_jsonl(release / "chunks.jsonl"):
            if chunk["file_id"] in files:
                file_chunks[chunk["file_id"]].append(chunk)
                if chunk["type"] == "table":
                    table_chunks[chunk["table_id"]].append(chunk)

        config = load_config()
        panels = reference_panels(candidates, table_chunks, evidence, config)
        manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
        fingerprint = manifest["corpus_fingerprint"]
        numeric_conflicts = defaultdict(set)
        if manifest.get("config", {}).get("k1", {}).get("numeric_cell_focus"):
            for findings in manifest.get("table_findings", {}).values():
                for finding in findings:
                    if finding.get("rule") == NUMERIC_RULE:
                        numeric_conflicts[finding["table_id"]].add((finding["r"], finding["c"]))
        old_spans = defaultdict(list)
        if legacy is not None:
            for findings in legacy.findings.values():
                for finding in findings:
                    old_spans[finding["chunk_id"]].extend(finding.get("removed_spans", []))
        old_text = legacy.replacements if legacy is not None else {}
        for file in read_jsonl(release / "files.jsonl"):
            file_id = file["file_id"]
            if file_id not in files:
                continue
            native, upright = load_native(corpus, fingerprint, file)
            if native is None:
                continue
            native_text = {item.self_ref: item for item in native.texts}
            targets = {}
            for chunk in file_chunks[file_id]:
                page, chunk_id = chunk["page"], chunk["chunk_id"]
                if page not in upright or page not in native.pages or chunk["pages"] != [page] or chunk["ocr"]:
                    continue
                options = [p for p in panels[file_id, page] if p.context == chunk["context"]]
                if not options or chunk["table_id"] in candidates:
                    continue
                existing = old_text.get(chunk_id, chunk["text"])
                if not existing:
                    continue
                if chunk["type"] == "text":
                    self.project_spans(chunk, native_text, native.pages[page].size.height, options, old_spans[chunk_id])
                elif chunk["type"] == "table":
                    table_id = chunk["table_id"]
                    if table_id not in targets:
                        table = records[table_id]
                        children = table_chunks[table_id]
                        native_part = len(table["parts"]) == 1 and table["parts"][0]["source_ref"].startswith("#/tables/")
                        same_context = all(child["pages"] == [page] and child["context"] == chunk["context"] for child in children)
                        targets[table_id] = (native_targets(table, evidence[table_id], options, children[0]["row_start"],
                                                           native_margin=native_margin,
                                                           numeric_conflicts=numeric_conflicts[table_id])
                                             if native_part and same_context and not analyse_table(table, children, config) else [])
                    self.project_cells(chunk, existing, targets[table_id])

    def project_spans(self, chunk, items, height, panels, old):
        claimed = [(panel.table_id, edit) for panel in panels for edit in text_edits(chunk, items, height, panel)]
        edits = [(tid, edit) for i, (tid, edit) in enumerate(claimed) if not any(
            edit["start"] < other["end"] and other["start"] < edit["end"]
            for other in [*old, *(entry[1] for j, entry in enumerate(claimed) if i != j)]
        )]
        if not edits:
            return
        combined = sorted([*old, *(edit for _, edit in edits)], key=lambda edit: edit["start"], reverse=True)
        text = chunk["text"]
        for edit in combined:
            text = text[:edit["start"]] + "\n" + text[edit["end"]:]
        self.replacements[chunk["chunk_id"]] = text.strip()
        self.findings[chunk["file_id"], chunk["page"]].append({"chunk_id": chunk["chunk_id"], "spans": [
            {**edit, "retained_table_id": tid} for tid, edit in edits]})

    def project_cells(self, chunk, existing, targets):
        slots = {slot for covered, _ in targets for slot in covered if chunk["row_start"] <= slot[0] < chunk["row_end"]}
        if not slots:
            return
        text, touched = mask_cells(dict(chunk, text=existing), slots)
        if not touched:
            return
        touched = {tuple(slot) for slot in touched}
        self.replacements[chunk["chunk_id"]] = text
        self.findings[chunk["file_id"], chunk["page"]].append({"chunk_id": chunk["chunk_id"], "cells": [
            {**proof, "masked_positions": sorted(covered & touched)} for covered, proof in targets if covered & touched]})

    def project(self, rows):
        for row in rows:
            chunk_id = row["chunk_id"]
            if chunk_id not in self.replacements:
                yield row
            elif self.replacements[chunk_id]:
                yield dict(row, text=self.replacements[chunk_id])

    def summary(self):
        findings = [finding for entries in self.findings.values() for finding in entries]
        cells = [cell for finding in findings for cell in finding.get("cells", ())]
        conflicts = {(cell["native_table_id"], cell["native_r"], cell["native_c"]) for cell in cells
                     if cell["action"] == "prefer_source_rows_and_columns"}
        return {"ruled_duplicate_spans_removed": sum(len(finding.get("spans", ())) for finding in findings),
                "ruled_duplicate_cell_positions_removed": sum(len(cell["masked_positions"]) for cell in cells),
                "ruled_native_margin_positions_removed": sum(len(cell["masked_positions"]) for cell in cells
                                                             if cell.get("native_box_extends_past_panel")),
                "ruled_uncertain_numeric_positions_removed": sum(len(cell["masked_positions"]) for cell in cells
                                                                 if cell["action"] == "remove_uncertain_numeric_duplicate"),
                "ruled_compound_cells_resolved": len(conflicts)}


def register_ruled_overlap(registry, load_projection):
    registry.register_reason(REASON, "INFO", "Retrieval prefers corroborated ruled cells over overlapping native content.", CHECK)

    def check(context, entity):
        if context.validator and context.validator["status"] != "pass":
            return []
        ids = entity["ids"]
        findings = load_projection().findings.get((ids["file_id"], ids["page"]))
        return [registry.signal(REASON, "page", ids, evidence={"parts": findings})] if findings else []

    registry.register_check(CHECK, check, "page", "1", limitations=(
        "Requires a fully corroborated single-part ruled panel and preserved, matching native text on an upright page.",
        "Changes only the retrieval view. Ambiguous, incomplete or unmatched native cells stay available.",
    ))
    return registry
