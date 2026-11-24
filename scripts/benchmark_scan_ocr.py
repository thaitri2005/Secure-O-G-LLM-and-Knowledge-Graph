"""Compare local OCR and numeric agreement on scans and rendered Track A grids."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass
from importlib.metadata import version
import io
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from rapidocr import RapidOCR

from graph_builder.corpus.text_metrics import normalize, words


@dataclass(frozen=True)
class Word:
    text: str
    box: tuple[float, float, float, float]
    confidence: float = 1.0


def overlap(first, second):
    left, top, right, bottom = first
    other_left, other_top, other_right, other_bottom = second
    intersection = max(0, min(right, other_right) - max(left, other_left)) * max(
        0, min(bottom, other_bottom) - max(top, other_top))
    if not intersection:
        return 0.0
    union = (right - left) * (bottom - top) + (other_right - other_left) * (other_bottom - other_top) - intersection
    return intersection / union


def numeric(word):
    """Keep internal punctuation, signs and units attached to a token."""
    token = normalize(word.text).strip(" ,;:()[]{}")
    return token if any(char.isdigit() for char in token) else ""


def positioned_matches(reference, prediction):
    """Match identical numeric tokens one-to-one by descending IoU; require at least 0.30."""
    by_token = {}
    for index, word in enumerate(reference):
        by_token.setdefault(numeric(word), []).append((index, word))
    candidates = []
    for index, predicted in enumerate(prediction):
        token = numeric(predicted)
        if token:
            for ref_index, expected in by_token.get(token, ()):
                score = overlap(expected.box, predicted.box)
                if score >= 0.30:
                    candidates.append((score, ref_index, index))
    used_ref, used_pred = set(), set()
    for _, ref_index, pred_index in sorted(candidates, key=lambda item: (-item[0], item[1], item[2])):
        if ref_index not in used_ref and pred_index not in used_pred:
            used_ref.add(ref_index)
            used_pred.add(pred_index)
    return used_ref, used_pred


def rapid_page(engine, path, scale):
    with Image.open(path) as source:
        image = source.convert("RGB")
    width, height = image.size
    if scale != 1:
        image = image.resize((round(width * scale), round(height * scale)), Image.Resampling.BICUBIC)
    sx, sy = image.width / width, image.height / height
    result = engine(np.asarray(image)[:, :, ::-1].copy(), return_word_box=True)
    if not result.txts:
        return [], []
    found = []
    for group in result.word_results or ():
        if not group:
            continue
        for token, score, polygon in group:
            if polygon is not None:
                x, y = zip(*polygon)
                found.append(Word(token, (min(x) / sx, min(y) / sy, max(x) / sx, max(y) / sy), score))
    return list(result.txts), found


def tesseract_page(path):
    command = ["tesseract", str(path), "stdout", "-l", "eng", "--psm", "11", "tsv"]
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60,
                            env={**os.environ, "OMP_THREAD_LIMIT": "2"})
    found = []
    # OCR may emit a literal quote at the start of a token. Tesseract TSV does not quote fields.
    for row in csv.DictReader(io.StringIO(result.stdout), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row["level"] == "5" and row["text"] and row["text"].strip():
            left, top, width, height = (int(row[key]) for key in ("left", "top", "width", "height"))
            found.append(Word(row["text"], (left, top, left + width, top + height), float(row["conf"]) / 100))
    return [word.text for word in found], found


def line_centers(mask):
    indices = np.flatnonzero(mask)
    groups = np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
    return [int(group[len(group) // 2]) for group in groups if len(group)]


def rapid_ruled_cells(engine, path):
    """Recognize bounded cells on a straight ruled grid using boundaries detected in the image."""
    with Image.open(path) as image:
        gray = np.asarray(image.convert("L"))
    rules = gray < 175
    rows = line_centers(rules.mean(axis=1) > 0.68)
    if len(rows) < 3:
        return []
    columns = line_centers(rules[rows[0]:rows[-1] + 1].mean(axis=0) > 0.85)
    if len(columns) < 3:
        return []

    crops, boxes = [], []
    for top, bottom in zip(rows, rows[1:]):
        for left, right in zip(columns, columns[1:]):
            patch = gray[top + 2:bottom - 1, left + 2:right - 1]
            y, x = np.where(patch < 175)
            if len(x) < 8:
                continue
            ink_left, ink_top, ink_right, ink_bottom = x.min(), y.min(), x.max() + 1, y.max() + 1
            ink = patch[ink_top:ink_bottom, ink_left:ink_right]
            pixels = np.pad(ink, 3, constant_values=255)
            crops.append(np.repeat(pixels[:, :, None], 3, axis=2))
            boxes.append((left + 2 + ink_left, top + 2 + ink_top, left + 2 + ink_right, top + 2 + ink_bottom))
    if not crops:
        return []

    engine.return_word_box = False
    result = engine.recognize_txt(crops)
    return [Word(text, box, score) for text, score, box in zip(result.txts, result.scores, boxes)
            if score >= 0.50 and len(text.split()) == 1]


def counts(reference, prediction, hits):
    return {"matched": hits, "reference": reference, "predicted": prediction}


def page_metrics(gold, answer_indices, output, predicted, numeric_only=False):
    ref_match, _ = positioned_matches(gold, predicted)
    answer_matches = len(ref_match.intersection(answer_indices))
    metrics = {
        "numeric_positioned": counts(sum(bool(numeric(w)) for w in gold),
                                     sum(bool(numeric(w)) for w in predicted), len(ref_match)),
        "numeric_answer_positioned": {"matched": answer_matches, "reference": len(answer_indices)},
    }
    if not numeric_only:
        expected_numbers = Counter(token for word in gold if (token := numeric(word)))
        actual_numbers = Counter(token for word in predicted if (token := numeric(word)))
        metrics["numeric_text_only"] = counts(sum(expected_numbers.values()), sum(actual_numbers.values()),
                                             sum((expected_numbers & actual_numbers).values()))
        expected = Counter(words(" ".join(word.text for word in gold).casefold()))
        actual = Counter(words(" ".join(output).casefold()))
        metrics["word_multiset"] = counts(sum(expected.values()), sum(actual.values()), sum((expected & actual).values()))
    return metrics


def evaluate_page(engine, annotation, image, ruled_grids=False):
    gold, answers = [], set()
    for entity in annotation["form"]:
        for item in entity["words"]:
            if not item["text"].strip():
                continue
            word = Word(item["text"], tuple(item["box"]))
            if entity["label"] == "answer" and numeric(word):
                answers.add(len(gold))
            gold.append(word)
    metrics, runtimes, predictions = {}, {}, {}
    for name, run in (
        ("rapid_native", lambda: rapid_page(engine, image, 1)),
        ("rapid_1_5x", lambda: rapid_page(engine, image, 1.5)),
        ("tesseract_sparse", lambda: tesseract_page(image)),
    ):
        started = time.perf_counter()
        output, predicted = run()
        runtimes[name] = time.perf_counter() - started
        predictions[name] = predicted
        metrics[name] = page_metrics(gold, answers, output, predicted)
    primary = predictions["rapid_native"]
    agreement, _ = positioned_matches(primary, predictions["tesseract_sparse"])
    metrics["rapid_confidence_0_90"] = page_metrics(
        gold, answers, [], [word for word in primary if word.confidence >= 0.90], numeric_only=True)
    metrics["cross_engine_agreement"] = page_metrics(
        gold, answers, [], [word for index, word in enumerate(primary) if index in agreement], numeric_only=True)
    if ruled_grids:
        started = time.perf_counter()
        cells = rapid_ruled_cells(engine, image)
        runtimes["rapid_ruled_cells"] = time.perf_counter() - started
        metrics["rapid_ruled_cells"] = page_metrics(gold, answers, [], cells, numeric_only=True)
        unassigned = [word for word in primary if numeric(word)
                      and all(overlap(word.box, cell.box) < 0.30 for cell in cells)]
        metrics["rapid_ruled_with_page_fallback"] = page_metrics(
            gold, answers, [], cells + unassigned, numeric_only=True)
    return {"metrics": metrics, "seconds": runtimes}


def summarize(pages):
    result = {}
    for name, metric_groups in next(iter(pages.values()))["metrics"].items():
        method = {}
        for group in metric_groups:
            totals = Counter()
            for page in pages.values():
                totals.update(page["metrics"][name][group])
            recall = round(totals["matched"] / totals["reference"], 4) if totals["reference"] else None
            method[group] = {**totals, "recall": recall}
            if "predicted" in totals:
                method[group]["precision"] = round(totals["matched"] / totals["predicted"], 4) if totals["predicted"] else None
        seconds = [page["seconds"][name] for page in pages.values() if name in page["seconds"]]
        if seconds:
            method["median_seconds"] = round(statistics.median(seconds), 3)
            method["total_seconds"] = round(sum(seconds), 3)
        result[name] = method
    return result


def render_grid(path, header_rows, output, font):
    """Render a small fixed sample from an annotated grid and retain word positions."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))[:header_rows + 8]
    columns = len(rows[0])
    if any(len(row) != columns for row in rows):
        raise ValueError(f"uneven row widths in {path}")
    widths = [max(40, round(max(font.getlength(row[i]) for row in rows)) + 20) for i in range(columns)]
    row_height = 27
    canvas = Image.new("L", (sum(widths) + 40, (len(rows) + 1) * row_height + 40), 239)
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 12), "Drilling report", font=font, fill=30)
    entities = []
    for row_index, row in enumerate(rows):
        left, top = 20, 30 + row_index * row_height
        for width, text in zip(widths, row):
            draw.rectangle((left, top, left + width, top + row_height), outline=150)
            x, y = left + 7, top + 5
            draw.text((x, y), text, font=font, fill=35)
            located = []
            for word in re.finditer(r"\S+", text):
                wx = x + font.getlength(text[:word.start()])
                located.append({"text": word.group(), "box": draw.textbbox((wx, y), word.group(), font=font)})
            if located:
                label = "header" if row_index < header_rows else "answer"
                entities.append({"label": label, "words": located})
            left += width
    entities.append({"label": "header", "words": [
        {"text": "Drilling", "box": draw.textbbox((20, 12), "Drilling", font=font)},
        {"text": "report", "box": draw.textbbox((20 + font.getlength("Drilling "), 12), "report", font=font)},
    ]})
    canvas.filter(ImageFilter.GaussianBlur(0.55)).save(output)
    return {"form": entities}


def funsd_samples(test_split):
    for path in sorted((test_split / "annotations").glob("*.json")):
        annotation = json.loads(path.read_text(encoding="utf-8"))
        yield path.stem, annotation, test_split / "images" / f"{path.stem}.png"


def grid_samples(gold, output, font):
    manifest = json.loads((gold / "tables.json").read_text(encoding="utf-8"))
    rendered = output.parent / "rendered-grids"
    rendered.mkdir(parents=True, exist_ok=True)
    for entry in manifest:
        if entry["format"] == "grid":
            image = rendered / f'{entry["id"]}.png'
            csv_path = gold / "tables" / Path(entry["csv"]).name
            annotation = render_grid(csv_path, entry["header_rows"], image, font)
            yield entry["id"], annotation, image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--funsd-test", type=Path, help="FUNSD dataset/testing_data")
    source.add_argument("--track-a-gold", type=Path, help="Track A data/gold/ingestion")
    parser.add_argument("--font", type=Path, help="TrueType font for rendering Track A grids")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.funsd_test:
        samples = list(funsd_samples(args.funsd_test))
        if len(samples) != 50:
            parser.error(f"expected all 50 FUNSD test annotations, found {len(samples)}")
        dataset = "funsd_test"
    else:
        if not args.font:
            parser.error("--track-a-gold requires --font")
        samples = list(grid_samples(args.track_a_gold, args.out, ImageFont.truetype(args.font, 14)))
        dataset = "track_a_rendered_grids"
    if not samples:
        parser.error("no benchmark samples found")
    engine = RapidOCR(params={"EngineConfig.onnxruntime.intra_op_num_threads": 2,
                              "EngineConfig.onnxruntime.inter_op_num_threads": 1})
    pages = {}
    for name, annotation, image in samples:
        pages[name] = evaluate_page(engine, annotation, image, ruled_grids=bool(args.track_a_gold))
        print(f"{len(pages)}/{len(samples)} {name}", flush=True)
    result = {"dataset": dataset, "pages": len(pages),
              "runtime": {"rapidocr": version("rapidocr"), "onnxruntime": version("onnxruntime"),
              "tesseract": subprocess.check_output(["tesseract", "--version"], text=True).splitlines()[0]},
              "summary": summarize(pages), "by_page": pages}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
