"""Benchmark OCR engines on scanned renderings of born-digital pages whose text layer is the reference (experiment E5).

Pages come from the Vietnamese Petroleum Law 12/2022/QH15 (Official Gazette PDFs) and the AK-3 end-of-well report.
Each page is rendered to an image under three scan conditions, saved as an image-only PDF, converted through the
same Docling path the corpus pipeline uses, and scored against the page's own text layer.

    python scripts/ocr_benchmark.py prepare
    python scripts/ocr_benchmark.py run --engines rapidocr-small rapidocr-medium easyocr
    python scripts/ocr_benchmark.py report
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import random
import sys
import time

import numpy as np
from PIL import Image, ImageFilter
import pypdfium2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from graph_builder.corpus.store import file_sha256  # noqa: E402
from graph_builder.corpus.text_metrics import compare  # noqa: E402
from graph_builder.corpus.vietnamese import text_profile  # noqa: E402

WORK = ROOT / "data/interim/ocr_benchmark"
SOURCES = {
    # Official Gazette copies of the Petroleum Law, downloaded from chinhphu.vn into data/raw/ocr_benchmark/.
    "luat12_1": {"path": "data/raw/ocr_benchmark/luat12_1.pdf", "language": "vi", "pages": [1, 3, 8, 14, 20, 25],
                 "url": "https://datafiles.chinhphu.vn/cpp/files/vbpq/2023/4/luat12_1.pdf"},
    "luat12_2": {"path": "data/raw/ocr_benchmark/luat12_2.pdf", "language": "vi", "pages": [4, 17],
                 "url": "https://datafiles.chinhphu.vn/cpp/files/vbpq/2023/4/luat12_2.pdf"},
    "ak3": {"path": "data/raw/gdr882_ak3_eowr.pdf", "language": "en", "pages": [2, 6, 12],
            "url": "https://gdr.openei.org/files/882/00%20AK-3%20EOW%20Report.pdf"},
}
CONDITIONS = {
    "clean300": {"dpi": 300},
    "scan200": {"dpi": 200, "rotate": 0.6, "blur": 0.6, "noise": 10, "jpeg": 45},
    "poor150": {"dpi": 150, "rotate": -1.2, "blur": 0.9, "noise": 18, "jpeg": 30},
}
ENGINES = {
    "vietocr": {"engine": "vietocr", "model_size": "small"},
    "rapidocr-small": {"engine": "rapidocr", "model_size": "small"},
    "rapidocr-medium": {"engine": "rapidocr", "model_size": "medium"},
    "easyocr": {"engine": "easyocr", "languages": ["vi", "en"], "model_size": "small", "scale": 2.0},
}


def degrade(image: Image.Image, condition: dict, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    image = image.convert("L")
    if condition.get("rotate"):
        image = image.rotate(condition["rotate"], resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255)
    if condition.get("blur"):
        image = image.filter(ImageFilter.GaussianBlur(condition["blur"]))
    if condition.get("noise"):
        array = np.asarray(image, dtype=np.float32) + rng.normal(0, condition["noise"], (image.height, image.width))
        image = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))
    if condition.get("jpeg"):
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=condition["jpeg"])
        image = Image.open(io.BytesIO(buffer.getvalue())).convert("L")
    return image


def prepare() -> None:
    cases = []
    for name, source in SOURCES.items():
        path = ROOT / source["path"]
        digest = file_sha256(path)
        with pypdfium2.PdfDocument(path) as pdf:
            for number in source["pages"]:
                page = pdf[number - 1]
                reference = page.get_textpage().get_text_range()
                for condition_name, condition in CONDITIONS.items():
                    case = f"{name}_p{number}_{condition_name}"
                    image = page.render(scale=condition["dpi"] / 72).to_pil()
                    image = degrade(image, condition, seed=random.Random(case).randint(0, 2**31))
                    target = WORK / "pdfs" / f"{case}.pdf"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    image.save(target, "PDF", resolution=condition["dpi"])
                    cases.append({"case": case, "source": name, "source_sha256": digest, "page": number,
                                  "language": source["language"], "condition": condition_name,
                                  "pdf": target.relative_to(ROOT).as_posix(), "reference": reference})
    (WORK / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Prepared {len(cases)} cases in {WORK}")


def document_text(document) -> str:
    from docling_core.types.doc import ContentLayer, TableItem, TextItem
    parts = []
    for item, _ in document.iterate_items(included_content_layers=set(ContentLayer), traverse_pictures=True):
        if isinstance(item, TableItem):
            parts.extend(cell.text for cell in item.data.table_cells)
        elif isinstance(item, TextItem):
            parts.append(item.text)
    return "\n".join(parts)


def run(engines: list[str], limit: int | None, conditions: list[str] | None = None) -> None:
    from graph_builder.corpus.convert import build_converter
    from graph_builder.corpus.ocr_engines import engine_fingerprint, ocr_config
    cases = json.loads((WORK / "cases.json").read_text(encoding="utf-8"))
    cases = [case for case in cases if not conditions or case["condition"] in conditions][:limit]
    results_path = WORK / "results.jsonl"
    done = set()
    if results_path.exists():
        done = {(r["engine"], r["case"]) for r in map(json.loads, results_path.read_text(encoding="utf-8").splitlines())}
    models = ROOT / "data/interim/ocr_models"
    for engine in engines:
        settings = ocr_config(ENGINES[engine])
        fingerprint = engine_fingerprint(models, settings)
        converter = build_converter({"ocr": settings, "table_mode": "fast"}, models, full_page_ocr=True)
        for case in cases:
            if (engine, case["case"]) in done:
                continue
            started = time.perf_counter()
            result = converter.convert(ROOT / case["pdf"])
            seconds = round(time.perf_counter() - started, 2)
            text = document_text(result.document)
            record = {"engine": engine, "case": case["case"], "language": case["language"],
                      "condition": case["condition"], "seconds": seconds,
                      **compare(case["reference"], text), "profile": text_profile(text),
                      "models": fingerprint["models"], "text": text}
            with results_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(engine, case["case"], seconds, record["cer"], record["word_recall"], flush=True)


def report() -> None:
    from collections import defaultdict
    rows = [json.loads(line) for line in (WORK / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    groups = defaultdict(list)
    for row in rows:
        groups[(row["engine"], row["language"], row["condition"])].append(row)
        groups[(row["engine"], row["language"], "all")].append(row)

    def mean(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 4) if values else None

    summary = []
    for (engine, language, condition), items in sorted(groups.items()):
        summary.append({"engine": engine, "language": language, "condition": condition, "pages": len(items),
                        "cer": mean(r["cer"] for r in items), "wer": mean(r["wer"] for r in items),
                        "word_recall": mean(r["word_recall"] for r in items),
                        "word_precision": mean(r["word_precision"] for r in items),
                        "vietnamese_word_recall": mean(r["vietnamese_word_recall"] for r in items),
                        "invalid_vietnamese_rate": mean(r["profile"]["invalid_vietnamese_rate"] for r in items),
                        "seconds_per_page": mean(r["seconds"] for r in items)})
    (WORK / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print("| Engine | Lang | Condition | Pages | CER | WER | Word recall | Word precision | Vietnamese word recall | Invalid Vietnamese | s/page |")
    print("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for s in summary:
        print(f"| {s['engine']} | {s['language']} | {s['condition']} | {s['pages']} | {s['cer']} | {s['wer']} | "
              f"{s['word_recall']} | {s['word_precision']} | {s['vietnamese_word_recall']} | "
              f"{s['invalid_vietnamese_rate']} | {s['seconds_per_page']} |")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("prepare", "run", "report"))
    parser.add_argument("--engines", nargs="+", default=list(ENGINES), choices=list(ENGINES))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--conditions", nargs="+", choices=list(CONDITIONS))
    args = parser.parse_args()
    {"prepare": prepare, "report": report}.get(args.command, lambda: run(args.engines, args.limit, args.conditions))()


if __name__ == "__main__":
    main()
