"""Expand pinned PDF portfolios into independently verifiable source documents."""
import hashlib
from pathlib import Path
import re
from pypdf import PdfReader

from .sources import verify_file, write_json


def split_portfolio(source: dict, root: Path) -> list[dict]:
    pdf = root / "data/raw" / f"{source['doc_id']}.pdf"
    verify_file(pdf, source)
    reader = PdfReader(pdf)
    children = []
    seen = set()
    for filename in sorted(reader.attachments):
        for content in reader.attachments[filename]:
            if not filename.casefold().endswith(".pdf"):
                continue
            digest = hashlib.sha256(content).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            slug = re.sub(r"[^a-z0-9]+", "_", Path(filename).stem.casefold()).strip("_") or "document"
            prefix = source["doc_id"].removesuffix("appendices") + f"appx_{len(children) + 1:02d}_"
            doc_id = prefix + slug[:64 - len(prefix)]
            path = root / "data/raw" / f"{doc_id}.pdf"
            record = {**source, "doc_id": doc_id, "title": Path(filename).stem,
                      "parent_doc_id": source["doc_id"], "original_filename": filename,
                      "sha256": digest, "bytes": len(content)}
            record.pop("portfolio", None)
            if path.exists():
                verify_file(path, record)
            else:
                path.write_bytes(content)
            PdfReader(path)
            children.append(record)
    if not children:
        raise ValueError("No PDF attachments found in portfolio")
    write_json(root / "data/interim" / f"{source['doc_id']}_sources.json", children)
    return children


def expand_portfolios(registry: list[dict], root: Path) -> list[dict]:
    result = []
    for source in registry:
        if source.get("portfolio"):
            result.extend(split_portfolio(source, root))
        else:
            result.append(source)
    return result
