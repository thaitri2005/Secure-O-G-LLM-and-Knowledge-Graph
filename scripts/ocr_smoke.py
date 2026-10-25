"""Generate a reproducible Vietnamese scan and optionally ingest/score it.

Run with the project virtual environment. Prefetch models before --run.
This checks a synthetic clean scan, not real-corpus production accuracy.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont
from graph_builder.ingestion.ocr_metrics import score_ocr
from graph_builder.ingestion.register import register_pdf

ROOT = Path(__file__).resolve().parents[1]
LINES = [
    "BÁO CÁO KỸ THUẬT",
    "Tiếng Việt và English trong cùng tài liệu.",
    "Nhiệt độ nước: 35,5 °C.",
    "Áp suất đo được: 12.5 bar.",
    "Độ sâu khảo sát: 1.955 m.",
    "Ngày kiểm tra: 24/10/2026.",
    "Kết quả: hệ thống hoạt động ổn định.",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/arial.ttf"))
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    directory = ROOT / "data/interim/ocr_smoke"
    directory.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1600, 2000), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(args.font), 48)
    for index, line in enumerate(LINES):
        draw.text((100, 180 + index * 120), line, fill="black", font=font)
    pdf = directory / "vietnamese.pdf"
    if not pdf.exists():
        image.save(pdf, resolution=150)
    registry = directory / "sources.json"
    # A fresh registry is generated from this deterministic synthetic fixture only.
    if not registry.exists():
        register_pdf(pdf, registry, "ocr_vi_smoke", "Vietnamese synthetic OCR smoke test", "synthetic")
    reference = "\n".join(LINES)
    (directory / "reference.txt").write_text(reference, encoding="utf-8")
    if args.run:
        subprocess.run([sys.executable, "-m", "graph_builder.ingestion", "run",
                        "--sources", str(registry), "--config", "configs/ingestion/vietnamese.json",
                        "--run-name", "ocr_vi_smoke"], cwd=ROOT,
                       env={**os.environ, "HF_HUB_OFFLINE": "1"}, check=True)
        output = ROOT / "data/interim/runs/ocr_vi_smoke/documents/ocr_vi_smoke.txt"
        metrics = score_ocr(reference, output.read_text(encoding="utf-8"))
        (directory / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(metrics))
    else:
        print(f"Prepared synthetic scan and reference under {directory}")


if __name__ == "__main__":
    main()
