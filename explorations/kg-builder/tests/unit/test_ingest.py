"""Corpus format, validation, and chunk offset acceptance tests."""
from __future__ import annotations
import unittest
import json
from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.core.config import KgbError, load_config
from kgbuilder.core.contracts import Document
from kgbuilder.build.ingest.corpus import load_corpus
from kgbuilder.build.parse.chunking import chunk_documents
from kgbuilder.core.text import write_jsonl


class IngestTest(unittest.TestCase):
    def test_wiki_corpus_json(self):
        path = PROJECT_ROOT / "configs/experiments/twowiki10.yaml"
        docs = load_corpus(load_config(path))
        self.assertEqual(len(docs), 24)
        self.assertEqual([d.doc_id for d in docs], [f"wiki_{i:03d}" for i in range(24)])
        self.assertEqual(docs[0].title, "Dangerously They Live")
        self.assertEqual(len(chunk_documents(docs, 2000)), 26)
        full = load_corpus(load_config(path, sets=["corpus.limit=null"]))
        self.assertEqual((len(full), len(chunk_documents(full, 2000))), (74, 81))
        questions = json.loads((PROJECT_ROOT / "data/benchmarks/2wiki/2wiki_30.json").read_text(encoding="utf-8"))[:10]
        titles = list(dict.fromkeys(f[0] for q in questions for f in q["supporting_facts"]))
        self.assertEqual(titles, [d.title for d in docs])
        source = self.tmp / "bad.json"
        for content, expected in [('[{"title":"x","text":"y"}]', "line 1, wiki_corpus_json"),
                                   ('{"a":1}', "JSON list"), ('[', "invalid JSON"),
                                   (json.dumps([{"idx":0,"title":"x","text":"y"}]*2), "duplicate wiki_000"),
                                   ('[null]', "line 1, wiki_corpus_json"),
                                   ('[{"idx":"0"}]', "idx must be an integer")]:
            source.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(KgbError) as caught:
                load_corpus(load_config(path, sets=[f"corpus.path={source.as_posix()}"]))
            self.assertEqual(caught.exception.code, 2)
            self.assertIn(expected, str(caught.exception))

    def setUp(self):
        self.tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/ingest" / self._testMethodName)

    def test_showcase(self):
        docs = load_corpus(load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml"))
        chunks = chunk_documents(docs, 2000)
        self.assertEqual((len(docs), len(chunks)), (3, 3))
        for doc, chunk in zip(docs, chunks):
            self.assertEqual(chunk.text, doc.text)
            self.assertEqual(doc.text[chunk.char_start:chunk.char_end], chunk.text)

    def test_webnlg_and_mine(self):
        web = load_corpus(load_config(PROJECT_ROOT / "configs/experiments/webnlg10.yaml"))
        self.assertEqual([d.doc_id for d in web], [f"webnlg_{i:04d}" for i in range(10)])
        cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", sets=[
            "corpus.path=data/benchmarks/mine/mine_5.jsonl", "corpus.format=mine_jsonl"])
        mine = load_corpus(cfg)
        self.assertEqual(len(mine), 5)
        self.assertEqual(mine[0].doc_id, "mine_4")
        self.assertEqual(mine[0].title, "Why Dinosaurs Fascinate Us")

    def test_input_failures_and_limit(self):
        path = self.tmp / "bad.jsonl"
        write_jsonl(path, [{"doc_id": "same", "text": "text"}, {"doc_id": "same", "text": "again"}, {"doc_id": "x", "text": ""}])
        cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", sets=[f"corpus.path={path.as_posix()}"])
        with self.assertRaises(KgbError) as caught:
            load_corpus(cfg)
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("line 2, doc_id", str(caught.exception))
        self.assertIn("line 3, text", str(caught.exception))
        cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", sets=[f"corpus.path={path.as_posix()}", "corpus.limit=1"])
        self.assertEqual(len(load_corpus(cfg)), 1)

    def test_long_chunks_offsets(self):
        doc = Document(doc_id="long", text=" ".join(["word"] * 200))
        chunks = chunk_documents([doc], 200)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertEqual(chunk.text, doc.text[chunk.char_start:chunk.char_end])
            self.assertLessEqual(len(chunk.text), 200)


if __name__ == "__main__": unittest.main()
