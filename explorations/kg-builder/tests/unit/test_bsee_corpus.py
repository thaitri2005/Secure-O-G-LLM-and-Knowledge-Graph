"""Synthetic corpus funnel, exclusion hashes, API10 isolation and deterministic selection."""
from __future__ import annotations

import csv
import io
import json
import unittest
import zipfile
from unittest.mock import patch

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.build.ingest.bsee_corpus import _collect, pii_flags, select, split_of, write_corpus
from kgbuilder.build.ingest.bsee_tables import build_tables
from kgbuilder.core.config import BseeCorpusConfig, BseeCorpusV2Config, ConfigError
from kgbuilder.core.text import cj, read_jsonl, sha256_file, sha256_text, write_json, write_jsonl
from unit.test_bsee_tables import table_fixture


def corpus_fixture(root, out):
    cfg = table_fixture(root)
    data = json.loads(cfg.source_manifest.read_text())
    entry = data["files"]["eWellEORRawData.zip"]
    path = PROJECT_ROOT / entry["path"]
    cases = json.loads((PROJECT_ROOT / "tests/fixtures/bsee/corpus_cases.json").read_text())
    text = cases["clean"]
    records = [["-1", "012345678900", "C", text], ["-2", "012345678901", "C", text],
               ["-3", "012345679000", "A", text + " Second."],
               ["-4", "012345679100", "A", text + " " + cases["honorific"]],
               ["-5", "012345679200", "A", "short"], ["-6", "012345679200", "A", "x" * 2001],
               ["-7", "999999999999", "A", text], ["-8", "012345679200", "A", ""],
               ["-9", "012345679200", "A", text + " Excluded."],
               ["-10", "012345679100", "A", text + " Excluded."]]
    spec = next(iter(entry["members"].values()))
    stream = io.StringIO(newline="")
    writer = csv.writer(stream); writer.writerow(spec["header"]); writer.writerows(records)
    with zipfile.ZipFile(path, "w") as z: z.writestr("eWellEORRawData/mv_eor_mainquery.txt", stream.getvalue())
    entry["sha256"] = sha256_file(path)
    data["data_sha256"] = sha256_text(cj({k: v for k, v in data.items() if k != "data_sha256"}))
    write_json(cfg.source_manifest, data)
    build_tables(cfg, out)
    return BseeCorpusConfig(source_manifest=cfg.source_manifest, tables=out, exclude_sn_eor=["-9"])


def corpus_v2_fixture(name):
    from unit.test_well_gold import gold_fixture, TEST_CONFIG
    gold = gold_fixture(complete=True)
    root = clean_dir(PROJECT_ROOT / "runs/_test" / name)
    source = root / "source"; source.mkdir()
    original = read_jsonl(gold["root"] / "corpus/corpus.jsonl")
    docs = original + [{"doc_id": "fresh_" + str(i), "text": "Invented operation number " + str(i) + "."} for i in range(9)]
    sources = [{"doc_id": doc["doc_id"], "API10": str(1000000000 + i), "API12": str(100000000000 + i * 100),
                "split": "dev" if i % 2 == 0 else "test", "EOR_OPERATION_CD": "A" if i % 3 == 0 else "B",
                "text_sha256": sha256_text(doc["text"])} for i, doc in enumerate(docs)]
    write_jsonl(source / "eligible.jsonl", docs)
    write_jsonl(source / "doc_sources.jsonl", sources)
    (source / "corpus.jsonl").write_bytes((gold["root"] / "corpus/corpus.jsonl").read_bytes())
    cfg = BseeCorpusV2Config(source_corpus=source, exclude_gold_config=TEST_CONFIG, gold_dev=3, gold_test=4)
    return root, cfg, [d["doc_id"] for d in original]


class BseeCorpusTest(unittest.TestCase):
    def test_v2_selection_repeat_and_integrity(self):
        from kgbuilder.build.ingest.bsee_corpus import select_gold_v2
        root, cfg, excluded = corpus_v2_fixture("recall_corpus_unit")
        out, repeat = root / "out", root / "repeat"
        stats = select_gold_v2(cfg.source_corpus, excluded, cfg, out)
        self.assertEqual(stats, select_gold_v2(cfg.source_corpus, excluded, cfg, repeat))
        for p in out.iterdir(): self.assertEqual(p.read_bytes(), (repeat / p.name).read_bytes())
        self.assertEqual((stats["n_dev"], stats["n_test"], stats["n_gold"]), (3, 4, 7))
        selected = json.loads((out / "selection.json").read_text())
        self.assertEqual(selected["strata_allocation"], {"dev": {"A": 1, "B": 2}, "test": {"A": 2, "B": 2}})
        self.assertEqual(selected["test_subset"], selected["test"])
        self.assertEqual([r["doc_id"] for r in read_jsonl(out / "corpus.jsonl")], selected["dev"] + selected["test"])
        self.assertEqual([r["doc_id"] for r in read_jsonl(out / "test_subset.jsonl")], selected["test"])
        self.assertFalse(set(excluded) & set(selected["dev"] + selected["test"]))
        self.assertEqual(selected["excluded"]["ids_sha256"], sha256_text(cj(sorted(excluded))))
        for name in ("eligible.jsonl", "doc_sources.jsonl"):
            self.assertEqual((out / name).read_bytes(), (cfg.source_corpus / name).read_bytes())
        sources = read_jsonl(cfg.source_corpus / "doc_sources.jsonl")
        docs = read_jsonl(cfg.source_corpus / "eligible.jsonl")
        with self.assertRaisesRegex(ConfigError, "excluded id not eligible"):
            select_gold_v2(cfg.source_corpus, ["absent"], cfg, root / "bad")
        for change in ("hash", "id", "api", "chunk"):
            changed_sources = [dict(row) for row in sources]
            changed_docs = [dict(row) for row in docs]
            if change == "hash": changed_sources[-1]["text_sha256"] = "different"
            if change == "id": changed_sources[-1]["doc_id"] = "different"
            if change == "api": changed_sources[-1]["API10"] = changed_sources[0]["API10"]
            if change == "chunk":
                for i in range(3, len(changed_docs)):
                    changed_docs[i]["text"] = "Invented operation. " * 200
                    changed_sources[i]["text_sha256"] = sha256_text(changed_docs[i]["text"])
            write_jsonl(cfg.source_corpus / "doc_sources.jsonl", changed_sources)
            write_jsonl(cfg.source_corpus / "eligible.jsonl", changed_docs)
            message = {"hash": "eligible/source mismatch", "id": "eligible/source mismatch", "api": "API10 shared with excluded gold", "chunk": "one whole chunk"}[change]
            with self.assertRaisesRegex(ConfigError, message):
                select_gold_v2(cfg.source_corpus, excluded, cfg, root / "bad")
        self.assertFalse((root / "bad").exists())

    def test_dev_subset_preserves_bytes_and_rejects_missing(self):
        from kgbuilder.build.ingest.bsee_corpus import split_subset
        from kgbuilder.core.config import ConfigError
        root = clean_dir(PROJECT_ROOT / "runs/_test/guided_subset_unit")
        first = b'{ "doc_id": "a", "text": "Invented first." }\r\n'
        last = b'{"doc_id":"b","text":"Invented last."}\n'
        (root / "corpus.jsonl").write_bytes(first + b'{"doc_id":"test","text":"Unused."}\n' + last)
        result = split_subset(root, ["b", "a"], "dev", "split-hash", root / "out")
        self.assertEqual((root / "out/dev.jsonl").read_bytes(), first + last)
        self.assertEqual(result["n"], 2)
        self.assertEqual(result["ids_sha256"], sha256_text(cj(["a", "b"])))
        self.assertEqual(result, split_subset(root, ["a", "b"], "dev", "split-hash", root / "repeat"))
        for ids, part in ((["missing"], "dev"), (["a"], "test")):
            with self.assertRaises(ConfigError): split_subset(root, ids, part, "hash", root / "bad")
        self.assertFalse((root / "bad").exists())

    def test_pii_and_split(self):
        cases = json.loads((PROJECT_ROOT / "tests/fixtures/bsee/corpus_cases.json").read_text())
        for key in ("honorific", "phone", "email", "context_name"):
            self.assertIn(key, pii_flags(cases[key]))
        self.assertEqual(pii_flags(cases["all_caps"]), [])
        for api in ("0123456789", "0123456790"):
            expected = "dev" if int(sha256_text("m7-split|42|" + api)[:8], 16) % 4 == 0 else "test"
            self.assertEqual(split_of(api, 42), expected)

    def test_funnel_and_repeat(self):
        root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/bsee_corpus")
        tables = clean_dir(PROJECT_ROOT / "runs/_test/bsee_corpus_tables")
        cfg = corpus_fixture(root, tables)
        out = clean_dir(PROJECT_ROOT / "runs/_test/bsee_corpus")
        repeat = clean_dir(PROJECT_ROOT / "runs/_test/bsee_corpus_repeat")
        stats = write_corpus(cfg, out)
        self.assertEqual(write_corpus(cfg, repeat), stats)
        for path in out.iterdir(): self.assertEqual(path.read_bytes(), (repeat / path.name).read_bytes())
        for key, count in {"rows_read": 10, "empty": 1, "too_short": 1, "too_long": 1, "api_not_joined": 1,
                           "planning_sample": 2, "pii_flagged": 1, "duplicate_texts": 1, "eligible": 2}.items():
            self.assertEqual(stats[key], count, key)
        sources = read_jsonl(out / "doc_sources.jsonl")
        self.assertEqual(len({r["API10"] for r in sources}), len(sources))
        self.assertEqual(stats["chunks"], stats["documents"])
        self.assertGreater(sum(stats["shortfalls"].values()), 0)
        self.assertNotIn("Excluded.", (out / "eligible.jsonl").read_text())
        self.assertNotIn("Mr. Example", (out / "eligible.jsonl").read_text())

    def test_allocation(self):
        cfg = BseeCorpusConfig(source_manifest="unused", tables="unused", gold_dev=3, gold_test=4)
        rows = [{"doc_id": str(i), "split": "test", "op": "a" if i < 6 else "b"} for i in range(10)]
        a = select(rows, cfg); b = select(reversed(rows), cfg)
        self.assertEqual(a, b)
        self.assertEqual(a["allocation"]["test"], {"a": 2, "b": 2})

    def test_streamed_screen_and_api10(self):
        root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/bsee_corpus_stream")
        tables = clean_dir(PROJECT_ROOT / "runs/_test/bsee_corpus_stream_tables")
        cfg = corpus_fixture(root, tables)
        texts = ["  " + "synthetic " * 22 + "\r\nEnd.  ", "different " * 22,
                 "Mr. Example " + "screened " * 22]
        rows = [{"values": {"SN_EOR": str(i), "API_WELL_NUMBER": "01234567890" + str(i),
                            "OPERATIONAL_NARRATIVE": value}, "raw_row_sha256": sha256_text(value)}
                for i, value in enumerate(texts)]
        rows.append(rows[0])
        with patch("kgbuilder.build.ingest.bsee_corpus.eor_rows", return_value=iter(rows)):
            db, stats, pii = _collect(iter(rows), tables, cfg)
        try:
            self.assertEqual(stats["duplicate_texts"], 1)
            self.assertEqual(stats["per_api10_removed"], 1)
            # API ...902 is absent from the fixture, so join exclusion precedes PII.
            self.assertEqual(stats["api_not_joined"], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM eligible").fetchone()[0], 1)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='raw'").fetchone())
            docs = [json.loads(row[0])["text"] for row in db.execute("SELECT doc FROM pool")]
            self.assertIn(texts[0].replace("\r\n", "\n").strip(), docs)
            self.assertFalse(any("Mr. Example" in text for text in docs))
        finally:
            db.close()
