"""Recover typed fields from raster report pages when two OCR readers agree."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cache
import math
import os
import re
import shutil
import subprocess
import unicodedata

from .ocr_engines import DEFAULT_MODELS, engine_fingerprint, model_files
from .ops_tables import grid_table_record, table_chunks
from .ruled_panels import key
from .text_layer import union

RULE = "scan_fields"
HEADER = ["Field", "Value"]
DATE = r"\d{4}[-./]\d{2}[-./]\d{2}"
LENGTH = r"\d[\d,]*(?:\.\d+)?\s*(?:['′]|ft|m)"
FIELDS = {
    "expiry date": ("below", DATE),
    "distribution date": ("below", DATE),
    "status": ("below", r"final|draft|approved"),
    "spud date": ("inline", DATE),
    "logging dates": ("inline", fr"{DATE}\s*[-–]\s*{DATE}"),
    "logging depths": ("inline", fr"{LENGTH}\s*[-–]\s*{LENGTH}"),
    "elevation": ("inline", fr"GL\s*:\s*{LENGTH}\s*RF\s*:\s*{LENGTH}"),
}


@dataclass(frozen=True)
class Line:
    text: str
    box: list[float]

    @property
    def height(self):
        return self.box[3] - self.box[1]

    @property
    def middle(self):
        return (self.box[1] + self.box[3]) / 2


def literal(text):
    normalized = unicodedata.normalize("NFC", text).translate(str.maketrans("’‘′", "'''"))
    return "".join(normalized.casefold().split())


@cache
def scan_runtime(models):
    command = shutil.which("tesseract")
    if command is None:
        raise ValueError("Scan table rules require Tesseract with the eng language data.")
    try:
        languages = subprocess.run([command, "--list-langs"], capture_output=True, text=True, check=True, timeout=7)
        version = subprocess.run([command, "--version"], capture_output=True, text=True, check=True, timeout=7)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Tesseract is unavailable for scan table rules.") from error
    if "eng" not in languages.stdout.splitlines() or not version.stdout.strip():
        raise ValueError("Scan table rules require Tesseract with the eng language data.")
    secondary = engine_fingerprint(models, {"engine": "rapidocr", "model_size": "small"})
    return {"tesseract": version.stdout.splitlines()[0], "ocr": secondary}


@cache
def rapid_reader(models, *, detect=True):
    from rapidocr import RapidOCR

    det, rec, cls = model_files(models, {"engine": "rapidocr", "model_size": "small"})
    if not all(path.is_file() for path in (det, rec, cls)):
        raise FileNotFoundError("Local RapidOCR small weights are required for scanned field verification")
    return RapidOCR(params={"Det.model_path": str(det), "Rec.model_path": str(rec), "Cls.model_path": str(cls),
                            "Global.use_det": detect, "Global.use_cls": detect,
                            "EngineConfig.onnxruntime.intra_op_num_threads": 1,
                            "EngineConfig.onnxruntime.inter_op_num_threads": 1})


def local_ocr(command, page, box, zoom, *, prefilter=None):
    import cv2
    import numpy as np
    import pymupdf

    area = pymupdf.Rect([coordinate / zoom for coordinate in box]) + (-1, -1, 1, 1)
    pixmap = page.get_pixmap(clip=area, matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    crop = np.frombuffer(pixmap.samples, np.uint8).reshape(pixmap.height, pixmap.width)
    padding = 12
    if prefilter == "enlarge":
        crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        padding = 18
    elif prefilter == "adaptive":
        crop = cv2.adaptiveThreshold(crop, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10)
    crop = cv2.copyMakeBorder(crop, padding, padding, padding, padding, cv2.BORDER_CONSTANT, value=255)
    return tesseract_line(command, crop)


def tesseract_line(command, crop, *, mode=7):
    import cv2

    success, encoded = cv2.imencode(".png", crop)
    if not success:
        return ""
    result = subprocess.run([command, "stdin", "stdout", "-l", "eng", "--psm", str(mode)],
                            input=encoded.tobytes(), capture_output=True, timeout=7,
                            env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    return result.stdout.decode("utf-8", errors="replace").strip() if result.returncode == 0 else ""


def corroborates(command, page, line, zoom):
    expected = literal(line.text)
    observed = literal(local_ocr(command, page, line.box, zoom))
    if observed == expected:
        return True
    if expected.isalpha():
        return literal(local_ocr(command, page, line.box, zoom, prefilter="adaptive")) == expected
    unit_marks = str.maketrans("", "", "'\"“”°")
    if observed.translate(unit_marks) != expected.translate(unit_marks):
        return False
    return any(literal(local_ocr(command, page, line.box, zoom, prefilter=method)) == expected
               for method in ("enlarge", "adaptive"))


def value_candidates(label, lines, direction, pattern, width):
    left, _, right, _ = label.box
    if direction == "below":
        return [item for item in lines if 0 < item.middle - label.middle <= 1.7 * label.height
                and abs(item.box[0] - left) <= .45 * label.height
                and re.fullmatch(pattern, item.text, re.I)]
    nearby = sorted((item for item in lines if 0 < item.box[0] - right < .30 * width
                     and abs(item.middle - label.middle) <= .46 * label.height), key=lambda item: item.box[0])
    candidates = []
    for stop in range(1, min(3, len(nearby)) + 1):
        selected = nearby[:stop]
        if any(b.box[0] - a.box[2] > 2 * label.height for a, b in zip(selected, selected[1:])):
            break
        text = " ".join(item.text for item in selected)
        if re.fullmatch(pattern, text, re.I):
            candidates.append(Line(text, union([item.box for item in selected])))
    return candidates


def detected_lines(page, clip, zoom, reader):
    import numpy as np
    import pymupdf

    bitmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
    image = np.frombuffer(bitmap.samples, np.uint8).reshape(bitmap.height, bitmap.width, 3)[:, :, ::-1].copy()
    result = reader(image)
    if not result.txts:
        return []
    lines = []
    for text, coords, score in zip(result.txts, result.boxes, result.scores, strict=True):
        if score >= .88:
            lx, ty = coords.min(axis=0)
            rx, by = coords.max(axis=0)
            lines.append(Line(text.strip(), [float(lx) + bitmap.x, float(ty) + bitmap.y,
                                             float(rx) + bitmap.x, float(by) + bitmap.y]))
    return lines


def read_page(page, failures=None, *, models=DEFAULT_MODELS):
    import pymupdf

    command = shutil.which("tesseract")
    if not command:
        return []
    zoom = min(2, 2000 / page.rect.width)
    height = page.rect.height if page.rect.height <= 2 * page.rect.width else .70 * page.rect.width
    clip = pymupdf.Rect(0, 0, page.rect.width, height)
    lines = detected_lines(page, clip, zoom, rapid_reader(models.resolve()))
    labels = {}
    for line in lines:
        if (name := key(line.text)) in FIELDS:
            labels.setdefault(name, []).append(line)
    fields = []
    for name, occurrences in labels.items():
        if len(occurrences) != 1:
            if failures is not None:
                failures.append(name)
            continue
        label, = occurrences
        direction, pattern = FIELDS[name]
        found = value_candidates(label, lines, direction, pattern, page.rect.width * zoom)
        if len(found) != 1 or key(local_ocr(command, page, label.box, zoom)) != name:
            if failures is not None:
                failures.append(name)
            continue
        value, = found
        if not corroborates(command, page, value, zoom):
            if failures is not None:
                failures.append(name)
            continue
        fields.append(([label.text.rstrip(": "), value.text],
                       [[coord / zoom for coord in item.box] for item in (label, value)]))
    return sorted(fields, key=lambda item: (item[1][0][1], item[1][0][0]))


def tall_scan_chunks(page, models, doc_id, number, max_chars, minimum):
    """Recover positioned text in strips after full-page OCR has missed a long scan."""
    import pymupdf

    from .chunking import language, pack

    width, height = page.rect.width, page.rect.height
    zoom = min(2, 2000 / width)
    reader = rapid_reader(models.resolve())
    recovered = []
    populated = 0
    for strip in range(math.ceil(height / width)):
        start, end = strip * width, min((strip + 1) * width, height)
        region = pymupdf.Rect(0, max(0, start - 20), width, min(height, end + 20))
        lines = sorted((line for line in detected_lines(page, region, zoom, reader)
                        if start <= line.middle / zoom < end and line.text),
                       key=lambda line: (line.middle, line.box[0]))
        if not lines:
            continue
        populated += 1
        text = "\n".join(line.text for line in lines)
        box = [0, start, width, end]
        for first, last in pack(text, max_chars):
            part = text[first:last]
            recovered.append(dict(doc_id=doc_id, type="text", text=part, section=None, section_path=[], page=number,
                                  pages=[number], regions=[dict(page=number, bbox=box)], source_spans=[], table_id=None,
                                  row_start=None, row_end=None, language=language(part), ocr=True, quality="review"))
    return recovered if populated >= 2 and sum(len("".join(chunk["text"].split())) for chunk in recovered) >= minimum else []


def repair_document(pdf, pages, chunks, tables, doc_id, max_chars, *, stacked_pages=(), models=DEFAULT_MODELS,
                    minimum=40):
    eligible = {page["page"]: page for page in pages if page["mode"] == "ocr" and page["page"] not in stacked_pages}
    tall = {number for number, page in eligible.items() if page["status"] == "missing"
            and 4 <= page["height"] / page["width"] <= 16}
    numbers = sorted(tall | {c["page"] for c in chunks if c["page"] in eligible
                             and any(label in key(c["text"]) for label in FIELDS if label != "status")})
    if not numbers:
        return chunks, tables, []
    findings = []
    try:
        import pymupdf
        with pymupdf.open(pdf) as source:
            for number in numbers:
                offset = next((i for i, chunk in enumerate(chunks) if min(chunk["pages"]) > number), len(chunks))
                if number in tall:
                    try:
                        rescued = tall_scan_chunks(source[number - 1], models, doc_id, number, max_chars, minimum)
                    except (ImportError, OSError, RuntimeError, ValueError):
                        rescued = []
                    if rescued:
                        chunks[offset:offset] = rescued
                        offset += len(rescued)
                        eligible[number].update(status="review", tiled_ocr=True)
                    findings.append({"page": number, "rule": RULE,
                                     "reason": "scan_strips_recovered" if rescued else "scan_strips_unconfirmed"})
                uncertain = []
                try:
                    fields = read_page(source[number - 1], uncertain, models=models)
                except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                    fields = []
                findings.extend({"page": number, "rule": RULE, "reason": f"scan_field_unconfirmed:{name.replace(' ', '_')}"}
                                for name in uncertain)
                if len(fields) < 2:
                    findings.append({"page": number, "rule": RULE, "reason": "scan_fields_not_corroborated"})
                    continue
                bbox = union([box for _, boxes in fields for box in boxes])
                ref = f"ocr:{RULE}:p{number}"
                table = grid_table_record(f"{doc_id}#{RULE}-{number}", doc_id, ref, number, bbox,
                                          [HEADER, *(row for row, _ in fields)])
                template = dict(doc_id=doc_id, section=None, section_path=[], ocr=True, quality="review")
                chunks[offset:offset] = table_chunks(table, template, max_chars)
                tables.append(table)
    except (ImportError, OSError, RuntimeError, ValueError):
        findings.append({"page": numbers[0], "rule": RULE, "reason": "scan_readers_unavailable"})
    return chunks, tables, findings
