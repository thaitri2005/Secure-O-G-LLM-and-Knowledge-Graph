"""Direct PDFium glyphs and vector rulings, independent of conversion output."""
from __future__ import annotations
from pathlib import Path
import math
import ctypes

def union(items: list) -> list | None:
    """Return the enclosing box of source glyphs or rectangles."""
    boxes = [item['bbox'] if isinstance(item, dict) else item for item in items]
    return [min((b[0] for b in boxes)), min((b[1] for b in boxes)), max((b[2] for b in boxes)), max((b[3] for b in boxes))] if boxes else None

def source_page(path: Path, number: int, upright: bool=False) -> dict:
    """Read visible glyphs and vector paths directly from the source PDF."""
    import pypdfium2 as pdfium
    from pypdfium2 import raw
    with pdfium.PdfDocument(path) as pdf:
        page = pdf[number - 1]
        textpage = page.get_textpage()
        width, height = page.get_size()
        rotation = page.get_rotation()
        rw, rh = (height, width) if rotation in (90, 270) else (width, height)

        def frame(box):
            l, b, r, t = box
            physical = {0: [l, rh - t, r, rh - b], 90: [b, l, t, r], 180: [rw - r, b, rw - l, t], 270: [rh - t, rw - r, rh - b, rw - l]}[rotation]
            if upright and rotation == 270:
                l, t, r, b = physical
                return [height - b, l, height - t, r]
            return physical
        chars = []
        clips = {}
        for i in range(textpage.count_chars()):
            value = textpage.get_text_range(i, 1)
            if not value.strip():
                continue
            bb = frame(textpage.get_charbox(i, loose=True))
            if bb[2] - bb[0] < 0.05 or bb[3] - bb[1] < 0.5:
                continue
            obj = textpage.get_textobj(i)
            pointer = ctypes.cast(obj.raw, ctypes.c_void_p).value if obj else None
            if pointer not in clips:
                boxes = []
                clip = raw.FPDFPageObj_GetClipPath(obj) if obj else None
                for path_index in range(max(0, raw.FPDFClipPath_CountPaths(clip))) if clip else []:
                    points = []
                    for segment_index in range(raw.FPDFClipPath_CountPathSegments(clip, path_index)):
                        segment = raw.FPDFClipPath_GetPathSegment(clip, path_index, segment_index)
                        x = ctypes.c_float()
                        y = ctypes.c_float()
                        if raw.FPDFPathSegment_GetPoint(segment, x, y):
                            points.append((x.value, y.value))
                    if points:
                        boxes.append(frame([min((p[0] for p in points)), min((p[1] for p in points)), max((p[0] for p in points)), max((p[1] for p in points))]))
                clips[pointer] = boxes
            cx, cy = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
            if any((not (clip[0] - 0.1 <= cx <= clip[2] + 0.1 and clip[1] - 0.1 <= cy <= clip[3] + 0.1) for clip in clips[pointer])):
                continue
            chars.append({'text': value, 'bbox': bb, 'index': i})
        rulings = []
        for obj in page.get_objects():
            if obj.type != raw.FPDF_PAGEOBJ_PATH:
                continue
            try:
                bb = frame(obj.get_bounds())
            except Exception:
                continue
            if bb[2] - bb[0] > 0.5 or bb[3] - bb[1] > 0.5:
                rulings.append(bb)
        if upright and rotation == 270:
            width, height = (height, width)
        rows = []
        for char in sorted(chars, key=lambda c: ((c['bbox'][1] + c['bbox'][3]) / 2, c['bbox'][0])):
            cy = (char['bbox'][1] + char['bbox'][3]) / 2
            if not rows or abs(cy - rows[-1]['cy']) > 2.2:
                rows.append({'cy': cy, 'chars': []})
            rows[-1]['chars'].append(char)
        words = []
        for row_id, row in enumerate(rows):
            run = []
            last = None
            for char in sorted(row['chars'], key=lambda c: c['bbox'][0]):
                gap = char['bbox'][0] - last['bbox'][2] if last else 0
                whitespace = last and any((textpage.get_text_range(j, 1).isspace() for j in range(last['index'] + 1, char['index'])))
                colon_boundary = last and last['text'] == ':' and any((c['text'].isalpha() for c in run))
                if last and (whitespace or colon_boundary or gap > max(2, 0.65 * (char['bbox'][3] - char['bbox'][1]))):
                    words.append({'text': ''.join((c['text'] for c in run)), 'bbox': union(run), 'row': row_id})
                    run = []
                run.append(char)
                last = char
            if run:
                words.append({'text': ''.join((c['text'] for c in run)), 'bbox': union(run), 'row': row_id})
        result = {'page': number, 'width': width, 'height': height, 'rotation': rotation, 'upright_for_pairing': upright and rotation == 270, 'chars': chars, 'words': words, 'rulings': rulings, 'text': textpage.get_text_range(), 'provenance': 'Direct PDFium glyphs and vector paths only.'}
        textpage.close()
        page.close()
        return result

def physical_box(bb: list | None, layer: dict) -> list | None:
    """Map an upright pairing box back to the displayed physical page."""
    if bb and layer['upright_for_pairing']:
        l, t, r, b = bb
        return [t, layer['width'] - r, b, layer['width'] - l]
    return bb
