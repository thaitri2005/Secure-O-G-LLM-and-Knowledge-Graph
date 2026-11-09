"""Scan the text layer of PDFs for source annotations such as "N records not printed" (A-414). No LLM, no network.

    python scripts/qa_annotation_scan.py --raw data/raw --out data/interim/overnight/b1/a414/scan \
        [--release <K1 release dir> --ledger <qa-ledger.json>]

Writes scan.json (per hit and per document), probes.json (variant phrases per page) and summary.json (per-family counts).
With --release the hits of documents present in the release (matched by SHA-256) are cross-referenced with the release text
and with the ledger signals. Output is deterministic (sorted keys, no timestamps)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from graph_builder.corpus.qa import annotations as ann  # noqa: E402
from graph_builder.corpus.qa.fidelity import iter_jsonl  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def page_texts(path: Path) -> list[str]:
    import pypdfium2 as pdfium
    out = []
    with pdfium.PdfDocument(path) as pdf:
        for index in range(len(pdf)):
            textpage = pdf[index].get_textpage()
            out.append(textpage.get_text_range())
            textpage.close()
    return out


def normal(text: str) -> str:
    return " ".join(text.lower().split())


def release_index(release: Path | None) -> dict:
    if release is None:
        return {}
    files = {row["sha256"]: row for row in iter_jsonl(release / "files.jsonl")}
    parts = ann.release_parts(release)
    return {"files": files, "parts": parts, "release": release}


def k1_text(index: dict, file_id: str) -> str:
    path = index["release"] / "text" / f"{file_id}.txt"
    return normal(path.read_text(encoding="utf-8")) if path.is_file() else ""


def k1_table_text(index: dict, file_id: str) -> str:
    out = []
    for table in iter_jsonl(index["release"] / "tables.jsonl"):
        if table["file_id"] == file_id:
            out.append(normal(json.dumps(table, ensure_ascii=False)))
    return " ".join(out)


def ledger_hits(ledger_path: Path | None) -> Counter:
    counter: Counter = Counter()
    if ledger_path is None:
        return counter
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    for document in ledger["documents"] if "documents" in ledger else ledger:
        for kind in ("pages", "tables"):
            for entity in document.get(kind, []):
                for signal in entity["signals"]:
                    if signal["code"] == ann.CODE:
                        evidence = signal["evidence"]
                        counter[(document["file_id"], evidence["position"]["page"], evidence["text"])] += 1
    return counter


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--release", type=Path, default=None)
    parser.add_argument("--ledger", type=Path, default=None)
    args = parser.parse_args()
    config = ann.load_config(args.config)
    probes = [(source, re.compile(source, re.IGNORECASE)) for source in config["probes"]["regexes"]]
    index = release_index(args.release)
    signals = ledger_hits(args.ledger)
    documents, hits_out, probe_rows = [], [], []
    totals: Counter = Counter()
    families: dict[str, Counter] = {}
    for pdf in sorted(args.raw.rglob("*.pdf")):
        row = {"document": pdf.name, "pages": 0, "error": None, "hit_pages": 0, "hits": 0, "rotated_pages_with_text_hit": 0}
        try:
            texts = page_texts(pdf)
            row["pages"] = len(texts)
            for number, text in enumerate(texts, start=1):
                found = {source: len(regex.findall(text)) for source, regex in probes}
                if any(found.values()):
                    probe_rows.append({"document": pdf.name, "page": number, "probes": {k: v for k, v in found.items() if v}})
            file_row = index.get("files", {}).get(sha256(pdf)) if index else None
            parts = index["parts"].get(file_row["file_id"]) if file_row else None
            scanned = ann.scan_pdf(pdf, config, parts)
        except Exception as error:  # noqa: BLE001 - one unreadable PDF must not stop the scan
            row["error"] = f"{type(error).__name__}: {str(error)[:120]}"
            documents.append(row)
            totals["documents_failed"] += 1
            continue
        row["rotated_pages_with_text_hit"] = len(scanned["rotated_pages"])
        row["page_errors"] = scanned["errors"]
        row["in_k1_release"] = bool(file_row)
        if file_row:
            body, tables = k1_text(index, file_row["file_id"]), k1_table_text(index, file_row["file_id"])
        for page, hits in sorted(scanned["pages"].items()):
            row["hit_pages"] += 1
            for hit in hits:
                row["hits"] += 1
                title = hit["title"] or {}
                record = {"document": pdf.name, "page": page, "text": hit["text"], "count": hit["count"], "pattern": hit["pattern"],
                          "bbox": hit["bbox"], "family": hit["family"], "title": title.get("text"),
                          "on_title_line": title.get("relation") in ("same_line", "same_segment"),
                          "table_match": hit["table"], "in_k1_release": bool(file_row)}
                if file_row:
                    phrase = normal(hit["text"])
                    record["k1_text_contains"] = phrase in body
                    record["k1_tables_contain"] = phrase in tables
                    record["ledger_signals"] = signals.get((file_row["file_id"], page, hit["text"]), 0)
                hits_out.append(record)
                counter = families.setdefault(hit["family"], Counter())
                counter["hits"] += 1
                counter["on_title_line"] += int(record["on_title_line"])
                counter["matched_to_table"] += int(bool(hit["table"]))
                counter["in_k1_release"] += int(bool(file_row))
                counter["k1_text_contains"] += int(record.get("k1_text_contains", False))
                counter["ledger_signal"] += int(record.get("ledger_signals", 0) > 0)
        documents.append(row)
        totals["documents"] += 1
        totals["pages"] += row["pages"]
        totals["hits"] += row["hits"]
        totals["hit_pages"] += row["hit_pages"]
        totals["documents_with_hits"] += int(row["hits"] > 0)
    args.out.mkdir(parents=True, exist_ok=True)
    limit = config["max_listed_hits"]["value"]
    summary = {"totals": dict(sorted(totals.items())), "families": {k: dict(sorted(v.items())) for k, v in sorted(families.items())},
               "pattern_counts": dict(sorted(Counter(h["pattern"] for h in hits_out).items())),
               "probe_pages": len(probe_rows),
               "probe_pages_without_pattern_hit": sum(1 for p in probe_rows if (p["document"], p["page"]) not in {(h["document"], h["page"]) for h in hits_out}),
               "documents_with_hits": [d["document"] for d in documents if d.get("hits")][:limit],
               "note": "patterns from configs/qa/annotations.json; counts are text-layer matches, not verified against the page image"}
    for name, payload in (("scan.json", {"documents": documents, "hits": hits_out}), ("probes.json", probe_rows), ("summary.json", summary)):
        (args.out / name).write_text(json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
