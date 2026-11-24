"""Render the pages of source PDFs to PNG images, so the application can show a cited page beside its passage.

    python platform/render_pages.py <pdf> --file-id <file_id> --out <folder>
    python platform/render_pages.py --release <K1 release folder> --pdfs <folder of source PDFs> --out <folder>

One PNG per page at 150 dpi, written as `<out>/<file_id>/p<n>.png` with page numbers from 1; this is the layout the
backend serves from `BACKEND_PAGE_IMAGES` (backend design §7). Pages already rendered are skipped, so a rerun costs
nothing. Only `pypdfium2` is used: PyMuPDF is AGPL and stays out of anything deployed.

In release mode each record of the release's `files.jsonl` names its PDF by `original_name`; the file is looked for in
the PDF folder (and its sub-folders) and its SHA-256 is checked against the record before any page is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

DPI = 150
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def render_pdf(pdf: Path, file_id: str, out: Path, dpi: int = DPI) -> tuple[int, int]:
    """Write the pages of `pdf` under `out/file_id`. Returns (pages written, pages skipped)."""
    import pypdfium2 as pdfium

    if not SAFE_ID.match(file_id):
        raise ValueError(f"file_id {file_id!r} is not usable as a folder name")
    folder = out / file_id
    folder.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    document = pdfium.PdfDocument(str(pdf))
    try:
        for number in range(1, len(document) + 1):
            target = folder / f"p{number}.png"
            if target.exists():
                skipped += 1
                continue
            page = document[number - 1]
            try:
                image = page.render(scale=dpi / 72).to_pil()
            finally:
                page.close()
            partial = target.with_suffix(".tmp")
            image.save(partial, format="PNG", optimize=True)
            partial.replace(target)
            written += 1
    finally:
        document.close()
    return written, skipped


def find_pdf(name: str, folder: Path) -> Path | None:
    return next((p for p in sorted(folder.rglob(name)) if p.is_file()), None)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def render_release(release: Path, pdfs: Path, out: Path, dpi: int = DPI) -> list[dict]:
    """Render every file of a K1 release whose PDF is in `pdfs`. One result row per file record."""
    results = []
    for line in (release / "files.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        row = {"file_id": record["file_id"], "original_name": record.get("original_name"), "status": "ok",
               "written": 0, "skipped": 0}
        pdf = find_pdf(record["original_name"], pdfs) if record.get("original_name") else None
        if pdf is None:
            row["status"] = "pdf not found"
        elif record.get("sha256") and sha256(pdf) != record["sha256"]:
            row["status"] = "sha256 differs from the release"
        else:
            row["written"], row["skipped"] = render_pdf(pdf, record["file_id"], out, dpi)
        results.append(row)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pdf", nargs="?", type=Path, help="one PDF (needs --file-id)")
    parser.add_argument("--file-id", help="the report's file_id: the folder name and the ID the API uses")
    parser.add_argument("--release", type=Path, help="a K1 release folder holding files.jsonl")
    parser.add_argument("--pdfs", type=Path, help="with --release: the folder holding the source PDFs")
    parser.add_argument("--out", type=Path, required=True, help="the page-image folder (BACKEND_PAGE_IMAGES)")
    parser.add_argument("--dpi", type=int, default=DPI)
    args = parser.parse_args(argv)
    started = time.time()
    if args.release:
        if not args.pdfs:
            parser.error("--release needs --pdfs")
        results = render_release(args.release, args.pdfs, args.out, args.dpi)
        for row in results:
            print(f"{row['file_id']}: {row['status']}, {row['written']} written, {row['skipped']} skipped")
        failed = [r for r in results if r["status"] != "ok"]
        print(f"{len(results) - len(failed)} of {len(results)} files rendered in {time.time() - started:.1f} s")
        return 1 if failed else 0
    if not args.pdf or not args.file_id:
        parser.error("give a PDF and --file-id, or --release and --pdfs")
    written, skipped = render_pdf(args.pdf, args.file_id, args.out, args.dpi)
    size = sum(p.stat().st_size for p in (args.out / args.file_id).glob("p*.png"))
    print(f"{args.file_id}: {written} written, {skipped} skipped, {size / 1e6:.1f} MB in {time.time() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
