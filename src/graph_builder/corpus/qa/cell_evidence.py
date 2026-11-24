"""Read-only cell evidence bound to a K1 release and the original PDF coordinate frame."""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import cache
import json
from pathlib import Path
import re
import subprocess

from ...ingestion.tables import table_views
from .. import casing_tables, column_alignment, complex_grids, hourly_operations, mud_properties, ruled_panels, source_grids
from ..numeric_cells import compact, contains, read_words, words_inside
from ..ocr_engines import DEFAULT_MODELS
from ..orientation import normalized_rotation, rotate_bbox
from ..store import atomic_write_json, atomic_write_jsonl, file_sha256, read_jsonl
from ..text_layer import source_page
from .fidelity import FidelityState, load_config as fidelity_config
from .form_overlap import valid_box
from .signals import Registry
from .table_overlap import load_native_document, positioned_box, tokens

CHECK = "table_cell_evidence"
REVIEW = "TABLE_CELL_SOURCE_REVIEW"
FRAME = "displayed_pdf_top_left_points"
DEPTH_HEADER = re.compile(r"(?:length|set at|setting depth|shoe depth|(?:top |bottom )?(?:md|tvd))\s*\((mgl|mmd|ft|m)\)", re.I)
NUMBER_WITH_UNIT = re.compile(r"([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\s*(mgl|mmd|ft|m))?", re.I)
UNITS = {"ft": "ft", "m": "m", "mgl": "mGL", "mmd": "mMD"}


def ident(cell):
    return cell["r"], cell["c"], cell["row_span"], cell["col_span"]


def cell_header(table, cell):
    if cell["r"] < table["header_rows"] or cell["col_span"] != 1:
        return None
    names = dict.fromkeys(row[cell["c"]] for row in table["grid"][:table["header_rows"]] if row[cell["c"]])
    return " / ".join(names) or None


def normalized_value(text, header, method, column):
    if header is None:
        return None
    if method == "hourly_operations" and column in (0, 1) and hourly_operations.CLOCK.fullmatch(text):
        hour, minute = text.split(":")
        return {"type": "time", "value": f"{int(hour):02d}:{minute}"}
    column_unit = DEPTH_HEADER.fullmatch(header) if method == "casing" else None
    number = NUMBER_WITH_UNIT.fullmatch(text) if column_unit else None
    if number and (number[2] is None or number[2].lower() == column_unit[1].lower()):
        return {"type": "number", "value": number[1].replace(",", ""), "unit": UNITS[column_unit[1].lower()]}
    return None


def base_row(table, cell, part):
    return {"file_id": table["file_id"], "doc_id": table["doc_id"], "table_id": table["table_id"],
            **{key: cell[key] for key in ("r", "c", "row_span", "col_span", "text", "is_header")},
            "column_header": cell_header(table, cell), "page": part["page"] if part else None,
            "source_ref": part["source_ref"] if part else None, "bbox": None, "bbox_frame": FRAME,
            "observed_text": None, "normalized": None, "method": None}


def cell_parts(table):
    for cell in table["cells"]:
        parts = [part for part in table["parts"]
                 if part["row_start"] <= cell["r"] and cell["r"] + cell["row_span"] <= part["row_end"]]
        yield cell, parts[0] if len(parts) == 1 else None


def omit(table, reason):
    for cell, part in cell_parts(table):
        yield dict(base_row(table, cell, part), status="unavailable", reason=reason)


def covered_word(word, region):
    left, top, right, bottom = region
    return (left <= (word[0] + word[2]) / 2 <= right
            and top <= (word[1] + word[3]) / 2 <= bottom)


def overlaps(box, other):
    x = min(box[2], other[2]) - max(box[0], other[0])
    y = min(box[3], other[3]) - max(box[1], other[1])
    return (x > min(box[2] - box[0], other[2] - other[0]) * 0.25
            and y > min(box[3] - box[1], other[3] - other[1]) * 0.65)


def proves_trimmed_prefix(item, part, cells, native_cells, cut, height):
    """Verify the producer's row shift and residual rectangle, including releases without the trim marker."""
    if (not cut or any(cell["r"] < cut < cell["r"] + cell["row_span"] for cell in native_cells)
            or [dict(cell, r=cell["r"] - cut + part["row_start"]) for cell in native_cells if cell["r"] >= cut] != cells):
        return False
    original = positioned_box(item.prov[0].bbox, height)
    retained = [positioned_box(cell.bbox, height) for cell in item.data.table_cells
                if cell.start_row_offset_idx >= cut and cell.text.strip()]
    if not valid_box(original) or not retained or not all(valid_box(box) for box in retained):
        return False
    expected = [original[0], max(original[1], min(box[1] for box in retained)), original[2], original[3]]
    return valid_box(part.get("bbox")) and all(abs(a - b) <= 0.05 for a, b in zip(expected, part["bbox"]))


class CellEvidence:
    def __init__(self, release: Path, corpus: Path | None, *, models: Path = DEFAULT_MODELS):
        self.release = release
        self.manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
        config = self.manifest["config"]["k1"].get("table_rules", {})
        self.allow_borderless = self.manifest["config"]["k1"].get("recover_borderless_grids", False)
        self.allow_broken_scans = self.manifest["config"]["k1"].get("recover_broken_scan_grids", False)
        self.allow_sparse_scans = self.manifest["config"]["k1"].get("recover_sparse_scan_rows", False)
        self.templates = hourly_operations.compile_templates(config.get("hourly_operations", {}).get("templates", []))
        self.operations_rule = config.get("operations_summary")
        self.corpus = corpus
        self.models = models
        self.pdf_lookup = FidelityState(release, corpus, fidelity_config())
        self.rows = []
        self.reviews = defaultdict(Counter)
        tables = defaultdict(list)
        for table in read_jsonl(release / "tables.jsonl"):
            tables[table["file_id"]].append(table)
        modes = {(page["file_id"], page["page"]): page["mode"] for page in read_jsonl(release / "pages.jsonl")}
        for file in self.pdf_lookup.files.values():
            owned = tables[file["file_id"]]
            if owned:
                self.rows.extend(self.read_file(file, owned, modes))
        for row in self.rows:
            if row["status"] == "review":
                self.reviews[row["table_id"]][row["reason"]] += 1

    def read_file(self, file, tables, modes):
        try:
            import pymupdf
        except ImportError:
            for table in tables:
                yield from omit(table, "source_reader_unavailable")
            return

        path, _ = self.pdf_lookup.locate_pdf(file)
        if path is None:
            for table in tables:
                yield from omit(table, "source_pdf_missing_or_digest_mismatch")
            return
        try:
            pdf = pymupdf.open(path)
        except (OSError, ValueError, RuntimeError):
            for table in tables:
                yield from omit(table, "source_pdf_unreadable")
            return
        with pdf:
            yield from self.read_tables(path, pdf, file, tables, modes)

    def read_tables(self, path, pdf, file, tables, modes):
        fingerprint = self.manifest["corpus_fingerprint"]
        native, work_pages = load_native_document(self.corpus, fingerprint, file) if self.corpus is not None else (None, {})
        items = {item.self_ref: item for item in native.tables} if native is not None else {}
        by_page = defaultdict(list)
        verified = defaultdict(list)
        for table in tables:
            if all("cell_sources" in part for part in table["parts"]):
                for part in table["parts"]:
                    verified[part["page"]].append((table, part))
                continue
            if len(table["parts"]) != len(table["pages"]) or {p["page"] for p in table["parts"]} != set(table["pages"]):
                yield from omit(table, "ambiguous_part_pages")
                continue
            assigned = defaultdict(list)
            for cell, part in cell_parts(table):
                if part is None:
                    yield dict(base_row(table, cell, None), status="unavailable", reason="cell_has_no_unique_part")
                else:
                    assigned[part["page"]].append(cell)
            for part in table["parts"]:
                if cells := assigned.get(part["page"]):
                    by_page[part["page"]].append((table, part, cells))

        for number, parts in verified.items():
            page = pdf[number - 1] if 1 <= number <= len(pdf) and modes.get((file["file_id"], number)) == "text" else None
            transition = normalized_rotation(work_pages.get(number, {}))
            for table, part in parts:
                yield from self.fragment_rows(table, part, page, transition)

        for page, page_parts in by_page.items():
            page_record = work_pages.get(page, {})
            transition = normalized_rotation(page_record)
            pdf_page = pdf[page - 1] if 1 <= page <= len(pdf) else None
            remaining = []
            scanned = modes.get((file["file_id"], page)) == "ocr"
            complex_tables = None
            raster_tables = None
            for table, part, cells in page_parts:
                if scanned and pdf_page is not None and part["source_ref"].startswith("ocr:scan_fields:"):
                    yield from self.scan_rows(table, part, cells, pdf_page)
                elif scanned and pdf_page is not None and part.get("scan_repairs"):
                    yield from self.scan_repair_rows(table, part, cells, pdf_page, items.get(part["source_ref"]))
                elif scanned and pdf_page is not None and part["source_ref"].startswith("ocr:scan_grid:"):
                    from ..scan_grids import RULE, read_page

                    if raster_tables is None:
                        try:
                            raster_tables = read_page(pdf_page, self.models, allow_broken=self.allow_broken_scans,
                                                      allow_sparse=self.allow_sparse_scans)
                        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                            raster_tables = []
                    yield from self.physical_rows(table, part, cells, raster_tables, RULE, ocr=True)
                elif pdf_page is not None and not transition and part["source_ref"].startswith(f"textlayer:{complex_grids.RULE}:"):
                    if complex_tables is None:
                        try:
                            complex_tables = [panel for panel in source_grids.table_panels(
                                path, pdf_page, True, allow_borderless=self.allow_borderless)
                                              if panel.get("rule") == complex_grids.RULE]
                        except (OSError, RuntimeError, ValueError):
                            complex_tables = []
                    yield from self.physical_rows(table, part, cells, complex_tables, complex_grids.RULE)
                else:
                    remaining.append((table, part, cells))
            page_parts = remaining
            if not page_parts:
                continue
            if (pdf_page is None or modes.get((file["file_id"], page)) != "text"
                    or (transition and transition[0] != pdf_page.rotation)
                    or (not transition and (pdf_page.rotation or (page_record.get("orientation") or {}).get("normalized")))):
                for table, part, cells in page_parts:
                    for cell in cells:
                        yield dict(base_row(table, cell, part), status="unavailable", reason="page_not_upright_text")
                continue

            @cache
            def drawings():
                return source_page(path, page, displayed_origin=True)

            @cache
            def read_panels(kind):
                return [result for _, result in ruled_panels.read_page(drawings(), [kind])]

            @cache
            def realigned_tables():
                words = [(word["text"], word["bbox"]) for word in drawings()["words"]]
                return [panel for panel in column_alignment.printed_tables(pdf_page)
                        if column_alignment.independently_readable(panel, words)]

            @cache
            def recovered_grids():
                words = [(word["text"], word["bbox"]) for word in drawings()["words"]]
                return [panel for panel in source_grids.ruled_grids(pdf_page)
                        if source_grids.independently_proven(pdf_page, panel, words)]

            authoritative = {}
            for table, part, _ in page_parts:
                which = part["source_ref"].split(":")[:2]
                if transition or len(table["parts"]) != 1 or len(which) != 2 or which[0] != "textlayer":
                    continue
                try:
                    rule = which[1]
                    if rule == "hourly_operations":
                        candidates = [result for _, _, result in hourly_operations.read_page(drawings(), self.templates)]
                    elif rule == "casing":
                        candidates = [result for _, result in casing_tables.read_page(drawings())]
                    elif rule == mud_properties.RULE:
                        candidates = [mud_properties.read_page(drawings())]
                    elif rule == column_alignment.RULE:
                        candidates = realigned_tables()
                    elif rule == source_grids.RULE:
                        candidates = recovered_grids()
                    elif rule == "operations_summary" and self.operations_rule:
                        from ..ops_tables import labels, read_page

                        candidates = [dict(result, grid=[labels(self.operations_rule), *result["rows"]])
                                      for result in read_page(drawings(), self.operations_rule) if result["status"] == "rebuilt"]
                        candidates = [result for result in candidates
                                      if ruled_panels.independently_readable(result, pdf_page.get_text("words", sort=True))]
                    elif rule == ruled_panels.RULE:
                        kind = part["source_ref"].split(":")[2:3]
                        candidates = [panel for panel in read_panels(kind[0]) if panel
                                      and ruled_panels.independently_readable(panel, pdf_page.get_text("words", sort=True))
                                      ] if kind and kind[0] in ruled_panels.TITLES else []
                    else:
                        continue
                except (OSError, RuntimeError, ValueError):
                    candidates = []
                box = part["bbox"]
                hits = [candidate for candidate in candidates if candidate and candidate["grid"] == table["grid"]
                        and casing_tables.inside(candidate["bbox"], box) and casing_tables.inside(box, candidate["bbox"])]
                if len(hits) == 1:
                    authoritative[table["table_id"]] = (rule, hits[0]["cell_boxes"])

            reference_cells = [(table_id, r, c, box) for table_id, (_, grid) in authoritative.items()
                               for r, row in enumerate(grid) for c, box in enumerate(row) if valid_box(box)]
            native_page = native.pages.get(page) if native is not None else None
            width, height = pdf_page.rect.width, pdf_page.rect.height
            back = (transition[0] - transition[1]) % 360 if transition else 0
            if back in (90, 270):
                width, height = height, width
            frame_matches = (native_page is not None and abs(native_page.size.width - width) <= 1
                             and abs(native_page.size.height - height) <= 1)
            native_text = page_record.get("mode") == "text" and page_record.get("rotation") == pdf_page.rotation
            words = []
            if frame_matches and native_text and any(part["source_ref"] in items for _, part, _ in page_parts):
                working_angle = transition[1] if transition else 0
                words = pdf_page.get_text("words", sort=working_angle == 0)
                if working_angle:
                    raw_box = pdf_page.rect * pdf_page.derotation_matrix
                    words = [(*rotate_bbox(list(word[:4]), raw_box.width, raw_box.height, working_angle), *word[4:])
                             for word in words]
                    words.sort(key=lambda word: (round(word[1] / 3), word[0]))
            for table, part, cells in page_parts:
                table_id = table["table_id"]
                if table_id in authoritative:
                    yield from self.rule_rows(table, *authoritative[table_id])
                    continue
                elif part["source_ref"].startswith("textlayer:"):
                    reason = "reconstruction_unmatched_or_unsupported"
                elif not native_text or part["source_ref"] not in items:
                    reason = "native_geometry_unavailable"
                elif not frame_matches:
                    reason = "native_page_size_differs"
                else:
                    item = items[part["source_ref"]]
                    yield from self.native_rows(table, item, native_page.size.height, words, reference_cells,
                                                native_page.size.width, part=part, cells=cells, rotation_back=back)
                    continue
                for cell in cells:
                    yield dict(base_row(table, cell, part), status="unavailable", reason=reason)

    def scan_rows(self, table, part, cells, page):
        import subprocess
        from ..scan_fields import HEADER, read_page

        try:
            fields = read_page(page, models=self.models)
        except (ImportError, OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            fields = []
        agreed = [HEADER, *(row for row, _ in fields)] == table["grid"]
        for cell in cells:
            row = base_row(table, cell, part)
            if cell["is_header"]:
                yield dict(row, status="unavailable", reason="generated_ocr_column_label")
            elif agreed:
                value, box = fields[cell["r"] - 1]
                yield dict(row, status="ocr_agreement", reason="two_ocr_readers_agree", observed_text=value[cell["c"]],
                           bbox=box[cell["c"]], method="rapidocr_and_tesseract")
            else:
                yield dict(row, status="review", reason="two_ocr_readers_could_not_reproduce_cell")

    def scan_repair_rows(self, table, part, cells, page, item):
        from subprocess import SubprocessError
        from ..scan_table_ink import native_box, read_printed

        plans = {(row["r"], row["c"]): row for row in part["scan_repairs"]}
        native = defaultdict(list)
        if item is not None and len(item.prov) == 1 and item.prov[0].page_no == part["page"]:
            for cell in item.data.table_cells:
                if cell.bbox and cell.row_span == cell.col_span == 1:
                    native[cell.start_row_offset_idx, cell.start_col_offset_idx].append(cell)
        for cell in cells:
            row = base_row(table, cell, part)
            key = cell["r"], cell["c"]
            proof = plans.get(key)
            if proof is None:
                yield dict(row, status="unavailable", reason="native_geometry_unavailable")
                continue
            original = native[key]
            observed = None
            if (len(original) == 1 and not page.rotation and compact(original[0].text) == proof["previous"]
                    and all(abs(a - b) <= .05 for a, b in zip(native_box(original[0], page.rect.height), proof["bbox"]))):
                try:
                    observed = read_printed(page, proof["bbox"], self.models, proof["previous"])
                except (ImportError, OSError, RuntimeError, ValueError, SubprocessError):
                    pass
            agreed = observed == proof["value"] == cell["text"]
            yield dict(row, status="ocr_agreement" if agreed else "review",
                       reason="printed_ink_two_readers_agree" if agreed else "printed_ink_repair_unconfirmed",
                       bbox=proof["bbox"], observed_text=observed, method="rapidocr_and_tesseract")

    @staticmethod
    def physical_rows(table, part, cells, candidates, method, *, ocr=False):
        """Match each physical cell and span before attaching a source assertion."""
        expected = table["grid"][part["row_start"]:part["row_end"]]
        matches = [panel for panel in candidates if panel["grid"] == expected
                   and all(abs(a - b) <= .05 for a, b in zip(panel["bbox"], part["bbox"], strict=True))]
        records = {(c["r"] + part["row_start"], c["c"]): c for c in matches[0]["cells"]} if len(matches) == 1 else {}
        for cell in cells:
            row = base_row(table, cell, part)
            record = records.get((cell["r"], cell["c"]))
            if record and all(cell[key] == record[key] for key in ("text", "row_span", "col_span")):
                box = matches[0]["cell_boxes"][record["r"]][record["c"]]
                if record.get("ocr_unreadable"):
                    yield dict(row, status="review", reason="ocr_cell_unreadable", method=method, bbox=box)
                else:
                    yield dict(row, status="ocr_agreement" if ocr else "source_supported",
                               reason="physical_cell_reproduced", method=method, bbox=box, observed_text=record["text"])
            else:
                yield dict(row, status="review", reason="physical_cell_could_not_be_reproduced", method=method)

    @staticmethod
    def fragment_rows(table, part, page, transition):
        from ..activity_detail import independent_words

        rule = part["source_ref"].split(":")[1]
        kind = rule if rule in {"daily_log", "well_completion", "split_row"} else "activity"
        if page is not None:
            angle = transition[1] if transition else page.rotation
            delta = (page.rotation - angle) % 360
            width, height = page.rect.width, page.rect.height
            if delta in (90, 270):
                width, height = height, width
            words = independent_words(page, angle)
        for source in part["cell_sources"]:
            cell = dict(source, row_span=1, col_span=1, is_header=source["r"] < table["header_rows"])
            row = base_row(table, cell, part)
            if page is None:
                yield dict(row, status="unavailable", reason=f"{kind}_fragment_page_unavailable")
                continue
            box = source["bbox"]
            padded = [box[0] - .5, box[1], box[2] + .5, box[3]]
            observed = " ".join(word[4] for word in words if covered_word(word, padded))
            row.update(method=f"ruled_{kind}_fragment", observed_text=observed,
                       bbox=rotate_bbox(box, width, height, delta) if delta else box)
            if tokens(observed) == tokens(source["text"]):
                yield dict(row, status="source_supported", reason=f"{kind}_fragment_matches_pdf")
            else:
                yield dict(row, status="review", reason=f"{kind}_fragment_text_differs")

    @staticmethod
    def rule_rows(table, rule, boxes):
        for cell in table["cells"]:
            row = base_row(table, cell, table["parts"][0])
            box = boxes[cell["r"]][cell["c"]]
            if table["grid"][cell["r"]][cell["c"]] != cell["text"]:
                yield dict(row, status="review", reason="cell_text_differs_from_ruled_grid", bbox=box,
                           observed_text=table["grid"][cell["r"]][cell["c"]], method=rule)
            elif cell["row_span"] != 1 or cell["col_span"] != 1 or not valid_box(box):
                yield dict(row, status="unavailable", reason="cell_has_no_visible_word_geometry")
            else:
                yield dict(row, status="source_supported", reason="ruled_grid_and_visible_words",
                           observed_text=cell["text"], bbox=box, method=rule,
                           normalized=normalized_value(cell["text"], row["column_header"], rule, cell["c"]))

    @staticmethod
    def native_rows(table, item, height, words, reference_cells, width, *, part=None, cells=None, rotation_back=0):
        part = table["parts"][0] if part is None else part
        cells = table["cells"] if cells is None else cells
        start, end = part["row_start"], part["row_end"]
        grid, _, native_records, headers = table_views(item)
        dropped = len(grid) - (end - start)
        repairs = {(row["r"], row["c"]): row for row in part.get("numeric_repairs", [])}
        for (r, c), repair in repairs.items():
            if 0 <= r < len(grid) and 0 <= c < len(grid[r]) and compact(grid[r][c]) == repair["previous"]:
                grid[r][c] = repair["value"]
        same_page = height is not None and len(item.prov) == 1 and item.prov[0].page_no == part["page"]
        suffix_matches = 0 <= dropped < len(grid) and grid[dropped:] == table["grid"][start:end]
        is_residual = ((table["header_rows"] == 0 if start == 0 else not part.get("header"))
                       and dropped >= max(1, headers))
        marker = part.get("native_trimmed_rows")
        trimmed = (same_page and suffix_matches and is_residual and marker in (None, dropped)
                   and proves_trimmed_prefix(item, part, cells, native_records, dropped, height))
        header_matches = (dropped == 0 and headers == table["header_rows"] if start == 0
                          else part.get("header") == grid[:dropped])
        if not (same_page and suffix_matches and (trimmed or (marker is None and header_matches))):
            for cell in cells:
                yield dict(base_row(table, cell, part), status="unavailable", reason="native_grid_or_page_mapping_changed")
            return
        native_cells = defaultdict(list)
        for cell in item.data.table_cells:
            native_cells[cell.start_row_offset_idx, cell.start_col_offset_idx, cell.row_span, cell.col_span].append(cell)
        for cell in cells:
            row = base_row(table, cell, part)
            r, c, rowspan, colspan = ident(cell)
            native_r = r - start + dropped
            matches = native_cells[native_r, c, rowspan, colspan]
            if trimmed:
                row["native_r"] = native_r
            box = positioned_box(matches[0].bbox, height) if len(matches) == 1 else None
            repair = repairs.get((native_r, c))
            if repair is not None and valid_box(box):
                region = repair["bbox"]
                observed = read_words(((word[4], word[:4]) for word in words), region)
                focus = repair.get("focus")
                geometry = contains(region, box)
                if focus is not None:
                    nearby = words_inside(((word[4], word[:4]) for word in words), box)
                    geometry = (valid_box(focus) and contains(region, focus) and len(nearby) == 1
                                and nearby[0][0] == repair["value"]
                                and all(abs(a - b) <= .1 for a, b in zip(nearby[0][1], focus)))
                verified = (rotation_back == 0 and rowspan == colspan == 1 and valid_box(region) and geometry
                            and compact(matches[0].text) == repair["previous"]
                            and observed == repair["value"] == cell["text"])
                yield dict(row, status="source_supported" if verified else "review", bbox=region,
                           observed_text=observed, method="ruled_numeric_cell",
                           reason="numeric_repair_matches_source" if verified else "numeric_repair_source_mismatch")
                continue
            if (not valid_box(box) or not (0 <= box[0] < box[2] <= width + 1 and 0 <= box[1] < box[3] <= height + 1)
                    or tokens(matches[0].text) != tokens(cell["text"])):
                yield dict(row, status="unavailable", reason="native_cell_box_or_text_unmapped")
                continue
            observed = " ".join(word[4] for word in words if covered_word(word, box))
            refs = [(table_id, r, c) for table_id, r, c, reference in reference_cells if overlaps(box, reference)]
            row.update(bbox=rotate_bbox(box, width, height, rotation_back) if rotation_back else box,
                       observed_text=observed, method="docling_region")
            if len({(table_id, r) for table_id, r, _ in refs}) > 1:
                reason = "native_box_spans_source_rows"
            elif len({(table_id, c) for table_id, _, c in refs}) > 1:
                reason = "native_box_spans_source_columns"
            elif tokens(observed) != tokens(cell["text"]):
                reason = "visible_text_differs_in_native_box"
            else:
                yield dict(row, status="text_matches_region", reason="native_box_text_matches")
                continue
            yield dict(row, status="review", reason=reason,
                       overlapping_source_cells=[{"table_id": t, "r": r, "c": c} for t, r, c in refs[:12]])

    def write(self, out: Path) -> dict:
        path = out / "cell_evidence.jsonl"
        count = atomic_write_jsonl(path, self.rows)
        summary = {"release_identity": self.manifest["identity"],
                   "release_checksums_sha256": file_sha256(self.release / "SHA256SUMS"),
                   "coordinate_frame": FRAME, "rows": count, "status": dict(Counter(row["status"] for row in self.rows)),
                   "reasons": dict(Counter(row["reason"] for row in self.rows))}
        summary_path = out / "cell_evidence_summary.json"
        atomic_write_json(summary_path, summary)
        return {"path": str(path), "summary": str(summary_path), "rows": count, "status": summary["status"]}


def register_cell_evidence(registry: Registry, load_evidence) -> Registry:
    registry.register_reason(REVIEW, "WARN", "A table cell disagrees with PDF evidence or spans multiple source cells.", CHECK)

    def check(context, entity):
        if context.validator and context.validator["status"] != "pass":
            return []
        ids = entity["ids"]
        reasons = load_evidence().reviews.get(ids["table_id"])
        return [registry.signal(REVIEW, "table", ids, evidence={"cells": sum(reasons.values()),
                                                                "reasons": dict(reasons)})] if reasons else []

    registry.register_check(CHECK, check, "table", "3", limitations=(
        "Native evidence requires a text page with a verified frame and an exact grid-to-part match. Region text alone leaves row and column assignment unverified.",
        "Source-level row and column evidence covers rebuilt casing, hourly operation, and mud-property grids on upright text pages.",
    ))
    return registry
