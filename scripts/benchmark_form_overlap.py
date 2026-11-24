"""Check source coverage before and after the K1 form deduplication retrieval view."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from time import perf_counter
from urllib.request import urlopen

from benchmark_track_a_ablation import (MODELS, configs, export_k1, load_k1_config, native_corpus, native_samples, options, read_json,
                                        references)
from prepare_forge_ddr_holdout import copy_verified

from graph_builder.corpus.qa.cli import run as run_qa
from graph_builder.corpus.qa.fidelity import tokens
from graph_builder.corpus.store import atomic_write_json, read_jsonl
from graph_builder.ingestion.attribution import page_texts


def stage_pdfs(manifest: dict, directory: Path) -> None:
    with TemporaryDirectory() as temp:
        for entry in manifest["documents"]:
            name = Path(entry["file"])
            if name.name != entry["file"]:
                raise ValueError(f"manifest PDF must be a filename: {name}")
            target = directory / name
            if target.exists():
                continue
            url = entry["source_url"]
            if url.startswith("https://github.com/"):
                url = url.replace("https://github.com/", "https://raw.githubusercontent.com/", 1).replace("/blob/", "/", 1)
            staged = Path(temp) / name
            with urlopen(url, timeout=45) as response, staged.open("wb") as stream:
                shutil.copyfileobj(response, stream)
            copy_verified(staged, target, entry["sha256"])


def released_pages(chunks: list[dict], view: dict[str, dict] | None = None, *, allow_table_overlap: bool = False) -> dict:
    pages = defaultdict(list)
    sections = defaultdict(set)
    form_pairs = defaultdict(list)
    for chunk in chunks:
        if view is not None and chunk["chunk_id"] not in view:
            if chunk["type"] != "form":
                if not (allow_table_overlap and chunk["type"] == "text" and chunk["pages"] == [chunk["page"]]):
                    raise ValueError(f"non-form chunk is missing: {chunk['chunk_id']}")
            else:
                continue
        row = chunk if view is None else view.get(chunk["chunk_id"], {"text": ""})
        if row["text"] == chunk["text"]:
            by_page = page_texts(chunk) if chunk.get("source_spans") else {chunk["page"]: chunk["text"]}
        elif chunk["type"] == "form":
            by_page = {chunk["page"]: row["text"]}
        elif allow_table_overlap and chunk["type"] in ("text", "table") and chunk["pages"] == [chunk["page"]]:
            by_page = {chunk["page"]: row["text"]}
        else:
            raise ValueError(f"non-form chunk was changed: {chunk['chunk_id']}")
        for page, text in by_page.items():
            key = chunk["doc_id"], page
            pages[key].append(text)
            sections[key].update(chunk.get("section_path", []))
            if chunk["type"] == "form":
                form_pairs[key].extend(line.replace(": ", " ", 1) for line in text.splitlines() if ": " in line)
    return {key: ("\n".join(parts), "\n".join(sorted(sections[key])), form_pairs[key]) for key, parts in pages.items()}


def coverage(sample, original, extracted):
    terms = {"words": Counter(), "numbers": Counter()}
    found = set()
    for page, (expected_words, expected_numbers) in enumerate(original, 1):
        text, sections, pairs = extracted.get((sample.name, page), ("", "", ()))
        flattened = " ".join(text.replace("|", " ").split())
        for probe in sample.critical.get(page, ()):
            if probe in pairs or re.search(rf"(?<!\w){re.escape(probe)}(?!\w)", flattened):
                found.add((page, probe))
        for kind, expected, present in zip(terms, (expected_words, expected_numbers), tokens(text + "\n" + sections)):
            excess = present - expected
            terms[kind].update(expected=sum(expected.values()), matched=sum((expected & present).values()),
                               surplus=sum(excess[token] for token in excess.keys() & expected.keys()))
    return {**{kind: dict(counts) for kind, counts in terms.items()}, "critical": len(found)}, found


def table_cells(source: dict, tables: list[dict]) -> dict:
    misses = []
    for probe in source.get("table_cells", []):
        candidate_values = []
        for table in tables:
            grid = table["grid"]
            for part in table["parts"]:
                if part["page"] != probe["page"]:
                    continue
                headers = [" ".join(dict.fromkeys(filter(None, (" ".join(row[col].split()) for row in part["header"]))))
                           for col in range(table["num_cols"])]
                columns = [col for col, header in enumerate(headers) if header == probe["column"]]
                if len(columns) != 1:
                    continue
                start = max(part["row_start"], table["header_rows"])
                candidate_values.extend(" ".join(row[columns[0]].split()) for row in grid[start:part["row_end"]]
                                        if " ".join(row[0].split()) == probe["row"])
        if candidate_values != [probe["value"]]:
            misses.append(probe)
    return {"expected": len(source.get("table_cells", [])), "missing": misses}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="fetch missing pinned source PDFs")
    parser.add_argument("--release", type=Path, help="reuse a matching K1 release")
    parser.add_argument("--corpus", type=Path, help="corpus for source-based QA or a new conversion")
    parser.add_argument("--native-seed", type=Path, help="reuse matching native conversions")
    parser.add_argument("--casing", action="store_true", help="enable the ruled casing table rule for a new release")
    parser.add_argument("--daily-header", action="store_true", help="enable daily cost and depth recovery for a new release")
    parser.add_argument("--require-all-probes", action="store_true",
                        help="fail if any pinned source phrase or table-cell probe is missing")
    args = parser.parse_args()
    if args.release and (args.casing or args.daily_header or args.native_seed):
        parser.error("--casing, --daily-header and --native-seed are only used to build a new release")
    if args.release and not args.corpus:
        parser.error("--release also needs --corpus to check the original PDFs and publish the retrieval view")
    manifest = read_json(args.manifest)
    if args.fetch:
        stage_pdfs(manifest, args.pdf_dir)
    samples = list(native_samples(args.manifest, args.pdf_dir))
    source_by_doc = {row["doc_id"]: row for row in manifest["documents"]}
    original = references(samples)

    timings = {}
    corpus_path, release = args.corpus, args.release
    if release is None:
        corpus_path = corpus_path or args.out / "corpus"
        config, k1, _ = configs(["running_line_min_pages", "generic_forms"], options())
        if args.casing:
            k1["table_rules"] = {"casing": load_k1_config()["table_rules"]["casing"]}
        if args.daily_header:
            k1["forms"]["daily_header"] = True
        tick = perf_counter()
        corpus = native_corpus(corpus_path, config, samples, args.native_seed)
        timings["process_seconds"] = perf_counter() - tick
        tick = perf_counter()
        release = Path(export_k1(corpus, "generic-forms", MODELS, k1)["export"])
        timings["k1_export_seconds"] = perf_counter() - tick

    files = list(read_jsonl(release / "files.jsonl"))
    expected_files = {(row["doc_id"], row["sha256"]) for row in manifest["documents"]}
    if {(row["doc_id"], row["sha256"]) for row in files} != expected_files:
        raise ValueError("K1 release documents and manifest do not match")
    tick = perf_counter()
    qa = run_qa(corpus_path, release, args.out / "qa", None, None, fidelity=corpus_path is not None,
                crossrep=True, form_overlap=True, table_overlap=False, ruled_table_overlap=False, compact_table_spans=False)
    timings["qa_and_view_seconds"] = perf_counter() - tick
    if "retrieval_view" not in qa:
        raise ValueError(f"QA could not publish a retrieval view. See {qa['ledger']} and {qa.get('source_validation', {})}.")

    chunks = list(read_jsonl(release / "chunks.jsonl"))
    view = {row["chunk_id"]: row for row in read_jsonl(Path(qa["retrieval_view"]["path"]))}
    tables = defaultdict(list)
    for table in read_jsonl(release / "tables.jsonl"):
        tables[table["doc_id"]].append(table)
    before, after = released_pages(chunks), released_pages(chunks, view)
    documents = {}
    for sample in samples:
        baseline, found_before = coverage(sample, original[sample.name], before)
        projection, found_after = coverage(sample, original[sample.name], after)
        expected = {(page, probe) for page, probes in sample.critical.items() for probe in probes}
        documents[sample.name] = {
            "family": sample.source_metadata["family"], "pages": sample.pages, "critical_expected": len(expected),
            "before": baseline, "after": projection, "lost_probes": sorted(found_before - found_after),
            "missing_probes": sorted(expected - found_after), "tables": table_cells(source_by_doc[sample.name], tables[sample.name]),
        }
    result = {"release": str(release), "qa": qa, "timings": timings, "documents": documents}
    path = args.out / "results.json"
    atomic_write_json(path, result)
    print(json.dumps({"results": str(path), "timings": timings, "projection": qa["retrieval_view"]}, indent=2))
    regression = any(doc["lost_probes"] for doc in documents.values())
    incomplete = any(doc["missing_probes"] or doc["tables"]["missing"] for doc in documents.values())
    return int(regression or (args.require_all_probes and incomplete))


if __name__ == "__main__":
    raise SystemExit(main())
