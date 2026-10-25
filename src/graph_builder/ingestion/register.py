"""Register a local PDF without uploading it or modifying the source file."""
import argparse
import json
import os
from pathlib import Path
from pypdf import PdfReader
from .sources import DOC_ID, sha256, write_json


def register_pdf(pdf: Path, registry: Path, doc_id: str, title: str,
                 license_id: str = "private", license_url: str = "") -> dict:
    pdf = pdf.resolve()
    if not DOC_ID.fullmatch(doc_id) or not title.strip():
        raise ValueError("A valid document ID and nonempty title are required")
    if not pdf.is_file() or not 0 < pdf.stat().st_size <= 50 * 1024 * 1024:
        raise ValueError("PDF must exist and be between 1 byte and 50 MiB")
    with pdf.open("rb") as stream:
        if b"%PDF-" not in stream.read(1024):
            raise ValueError("File does not have a PDF signature")
    reader = PdfReader(pdf)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported")
    if not 0 < len(reader.pages) <= 300:
        raise ValueError("PDF must contain between 1 and 300 pages")
    records = json.loads(registry.read_text(encoding="utf-8")) if registry.exists() else []
    if not isinstance(records, list) or any(not isinstance(r, dict) or r.get("doc_id") == doc_id for r in records):
        raise ValueError("Registry must be an array with no duplicate document ID")
    try:
        location = os.path.relpath(pdf, registry.resolve().parent)
    except ValueError:
        location = str(pdf)
    record = {"doc_id": doc_id, "title": title, "path": location,
              "license": {"id": license_id, "url": license_url},
              "sha256": sha256(pdf), "bytes": pdf.stat().st_size}
    write_json(registry, records + [record])
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--license-id", default="private")
    parser.add_argument("--license-url", default="")
    args = parser.parse_args()
    try:
        record = register_pdf(args.pdf, args.registry, args.doc_id, args.title, args.license_id, args.license_url)
        print(f"Registered {record['doc_id']}: {record['bytes']} bytes, SHA256={record['sha256']}")
        return 0
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
