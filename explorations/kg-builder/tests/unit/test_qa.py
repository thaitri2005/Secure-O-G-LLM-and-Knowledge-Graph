"""Hand cases for fixed retrieval, reader formatting and HippoRAG metrics."""
from __future__ import annotations

import json
import unittest
import urllib.error
from unittest.mock import patch, MagicMock

import numpy as np

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.core.config import ConfigError, KgbError, QaConfig
from kgbuilder.core.contracts import GraphRecord, Entity, Document
from kgbuilder.core.text import write_json, write_jsonl
from kgbuilder.serve import qa


class QaTest(unittest.TestCase):
    def setUp(self):
        self.record = GraphRecord.model_validate_json((PROJECT_ROOT / "tests/fixtures/graph_small.json").read_text(encoding="utf-8"))
        self.tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/qa" / self._testMethodName)
        self.config = QaConfig(name="qa_test", build_config=PROJECT_ROOT / "configs/experiments/twowiki10.yaml",
                               questions=self.tmp / "questions.json", graphs={"A0": PROJECT_ROOT / "runs/_test/qa_unit"},
                               seed_linking="exact", fact_order="confidence")

    def test_seeds(self):
        for question, ids in [
                ("Where did Alice work before Nova AI?", ["e3", "e1"]),
                ("Who operates International Business Machines?", ["e4"]),
                ("Is the ibm the same?", ["e4"]), ("nothing here", []),
                ("alices ibmish", [])]:
            self.assertEqual(qa.seeds(self.record, question, 5), ids)
        self.assertEqual(qa.seeds(self.record, "Where did Alice work before Nova AI?", 1), ["e3"])
        labs = Entity(entity_id="e5", name="Labs", aliases=[], kind="entity", mention_ids=[], resolver="identity")
        record = self.record.model_copy(update={"entities": self.record.entities + [labs]})
        self.assertEqual(qa.seeds(record, "Who owns Acme Labs?", 5), ["e2"])
        entities = [e.model_copy(update={"kind": "literal"}) if e.entity_id == "e3" else e for e in self.record.entities]
        record = self.record.model_copy(update={"entities": entities})
        self.assertEqual(qa.seeds(record, "Where did Alice work before Nova AI?", 5), ["e1"])
        # Identical spans may seed more than one id, in id order.
        twin = labs.model_copy(update={"name": "Alice"})
        record = self.record.model_copy(update={"entities": self.record.entities + [twin]})
        self.assertEqual(qa.seeds(record, "Alice", 5), ["e1", "e5"])

    def test_bfs(self):
        for updates, expected, docs in [
                ({"hops": 1}, ["s1", "s2"], ["d1"]),
                ({"hops": 2}, ["s1", "s2", "s3"], ["d1", "d2"]),
                ({"hops": 2, "max_statements": 2}, ["s1", "s2"], ["d1"]),
                ({"hops": 2, "k": 1}, ["s1", "s2", "s3"], ["d1"])]:
            ids, statements, seed_ids = qa.graph_retrieve(self.record, "Where did Alice work?", self.config.model_copy(update=updates))
            self.assertEqual([s.statement_id for s in statements], expected)
            self.assertEqual(ids, docs); self.assertEqual(seed_ids, ["e1"])
        statements = [s.model_copy(update={"confidence": .99}) if s.statement_id == "s2" else s for s in self.record.statements]
        record = self.record.model_copy(update={"statements": statements})
        self.assertEqual([s.statement_id for s in qa.graph_retrieve(record, "Alice", self.config)[1]], ["s2", "s1", "s3"])
        statements = [s.model_copy(update={"status": "rejected", "reasons": ["test"]}) if s.statement_id == "s3" else s for s in statements]
        record = self.record.model_copy(update={"statements": statements})
        self.assertEqual([s.statement_id for s in qa.graph_retrieve(record, "Alice", self.config)[1]], ["s2", "s1"])
        self.assertEqual(qa.graph_retrieve(record, "nobody", self.config), ([], [], []))

    def test_robust_seeds(self):
        entities = [Entity(entity_id=eid, name=name, aliases=[], kind="entity", mention_ids=[], resolver="identity")
                    for eid, name in (("e_a", "Anne Baldwin Gust Brown"), ("e_p", "Pat Brown"),
                                      ("e_e", "Edith of Wessex"), ("e_j", "John Lyon, 5th Earl of Strathmore and Kinghorne"))]
        record = self.record.model_copy(update={"entities": entities})
        question = "Who is Anne Gust Brown's father-in-law?"
        self.assertEqual(qa.seeds(record, question, 5, "exact"), [])
        self.assertEqual(qa.seeds(record, question, 5, "robust"), ["e_a"])
        self.assertEqual(qa.seeds(record, question.replace("'", "\u2019"), 5, "robust"), ["e_a"])
        for mode in ("exact", "robust"):
            self.assertEqual(qa.seeds(record, "Who is Edith Of Wessex's mother-in-law?", 5, mode), ["e_e"])
        self.assertEqual(qa.seeds(record, "Who was John Lyon?", 5, "robust"), [])
        self.assertEqual(qa.seeds(record, "Did Anne Gust Brown marry Jerry Brown?", 5, "robust"), ["e_a"])
        self.assertEqual(qa.seeds(record, "Did Anne Gust Brown marry Pat Brown?", 1, "robust"), ["e_p"])

    def test_relevance_and_memo(self):
        cfg = self.config.model_copy(update={"fact_order": "relevance", "max_statements": 1})
        question = "Alice, who operates laboratories?"
        chosen = qa.graph_retrieve(self.record, question, cfg, self.encode)
        self.assertEqual([s.statement_id for s in chosen[1]], ["s3"])
        self.assertEqual(chosen[0], ["d2"])
        legacy = qa.graph_retrieve(self.record, question, cfg.model_copy(update={"fact_order": "confidence"}))
        self.assertEqual([s.statement_id for s in legacy[1]], ["s1"])
        flagged = self.record.model_copy(update={"statements": [
            s.model_copy(update={"reasons": ["weak_evidence"]}) if s.statement_id == "s3" else s
            for s in self.record.statements]})
        self.assertEqual([s.statement_id for s in qa.graph_retrieve(flagged, question, cfg, self.encode)[1]], ["s1"])
        with self.assertRaises(ValueError):
            qa.graph_retrieve(self.record, question, cfg)
        calls = []
        def encode(values):
            calls.extend(values)
            return self.encode(values)
        memo = qa.memo_encode(encode)
        for q in (question, "Where did Alice work before Nova AI?", "Who operates International Business Machines?", "nobody", question):
            self.assertEqual(qa.graph_retrieve(self.record, q, cfg, memo), qa.graph_retrieve(self.record, q, cfg, self.encode))
        self.assertEqual(len(calls), len(set(calls)))

    def test_reader_and_hybrid(self):
        self.assertEqual(qa.hybrid(["d2"], ["d1", "d2", "d3"], 2), ["d2", "d1"])
        self.assertEqual(qa.fact_lines(self.record, self.record.statements),
                         ["- Alice works_at Acme Labs", "- Alice works_at Nova AI", "- IBM operates Acme Labs"])
        messages = qa.reader_messages("Who operates Acme Labs?", [self.record.documents[1]], ["- IBM operates Acme Labs"])
        self.assertEqual(messages[0], {"role": "system", "content": qa.SYSTEM})
        self.assertEqual(messages[1]["content"], "Passages:\n[1] IBM: IBM operates Acme Labs.\n\nFacts:\n- IBM operates Acme Labs\n\nQuestion: Who operates Acme Labs?\nAnswer:")
        self.assertNotIn("Facts:", qa.reader_messages("q", [], [])[1]["content"])
        for content, expected in [("Answer: Paris.\nmore", "Paris."), ("  \n yes", "yes"), ("", ""), ("aNsWeR: no", "no")]:
            self.assertEqual(qa.clean_answer(content), expected)

    def test_metrics(self):
        norm = qa.normalizer()
        self.assertEqual(norm("The  Roots!"), "roots")
        self.assertEqual(qa.exact_match("Salad By The Roots", "salad by the roots.", norm), 1.)
        self.assertEqual(qa.token_f1("Pat Brown", "Edmund Pat Brown", norm), .8)
        self.assertEqual(qa.token_f1("Salad By The Roots", "Salad", norm), .5)
        self.assertEqual(qa.token_f1("yes", "no", norm), 0.)
        self.assertEqual(qa.token_f1("", "", norm), 0.)
        for retrieved, k, expected in [(["B", "C", "A"], 2, .5), (["B", "C", "A"], 5, 1.), ([], 5, 0.)]:
            self.assertEqual(qa.recall_at({"A", "B"}, retrieved, k), expected)
        self.assertEqual(qa.recall_at(set(), ["A"], 5), 0.)

    @staticmethod
    def encode(values):
        vocab = ["alice", "ibm", "operates"]
        vectors = np.array([[v.lower().split().count(w) for w in vocab] for v in values], dtype=float)
        return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1)

    def test_text_rank(self):
        docs = [Document(doc_id="z", text="alice"), Document(doc_id="b", text="ibm"), Document(doc_id="a", text="ibm")]
        self.assertEqual(qa.text_rank(docs, self.encode([d.text for d in docs]), "alice", self.encode), ["z", "a", "b"])
        # A difference below rounding precision must still break by id.
        self.assertEqual(qa.text_rank(docs, np.array([[0,0,0], [0.0000001,0,0], [0,0,0]]), "alice", self.encode), ["a", "b", "z"])

    def test_graph_stats(self):
        questions = [{"evidences": [["Alice", "employer", "Acme Labs"], ["IBM", "owner of", "Nova AI"]]}]
        stats = qa.graph_stats(self.record, None, questions)
        self.assertEqual((stats["evidence_pair_recall"], stats["evidence_entity_recall"], stats["statements"], stats["docs_with_statements"], stats["build"]), (.5, 1., 3, 2, None))
        entities = [e.model_copy(update={"kind": "literal"}) if e.entity_id == "e3" else e for e in self.record.entities]
        stats = qa.graph_stats(self.record.model_copy(update={"entities": entities}), {"er_reduction": .2}, questions)
        self.assertEqual((stats["evidence_entity_recall"], stats["entities"], stats["entities_literal"]), (1., 3, 1))
        self.assertEqual(stats["build"]["er_reduction"], .2)
        self.assertEqual(qa.graph_stats(self.record, None, [{"evidences": [["Acme Labs", "anything", "Alice"]]}])["evidence_pair_recall"], 1.)

    def question(self):
        return {"_id": "q1", "type": "test", "question": "Alice", "answer": "yes", "supporting_facts": [["Alice", 0]], "evidences": [["Alice", "works at", "Acme Labs"]]}

    def test_inputs(self):
        question = self.question()
        write_json(self.config.questions, [question])
        self.assertEqual(qa.load_questions(self.config.questions, 1), [question])
        for data, message in [({}, "JSON list"), ([{}], "row 0"), ([], "no selected")]:
            write_json(self.config.questions, data)
            with self.assertRaisesRegex(ConfigError, message): qa.load_questions(self.config.questions, None)
        self.config.questions.write_text("[", encoding="utf-8")
        with self.assertRaises(ConfigError): qa.load_questions(self.config.questions, None)
        write_json(self.config.questions, [question])
        graph_dir = clean_dir(PROJECT_ROOT / "runs/_test/qa_unit" / self._testMethodName)
        write_json(graph_dir / "graph.json", self.record.model_dump(mode="json"))
        cfg = self.config.model_copy(update={"graphs": {"A0": graph_dir}})
        inputs = qa.prepare(cfg)
        self.assertIsNone(inputs.metrics["A0"])
        self.assertEqual([d.doc_id for d in inputs.documents], ["d1", "d2"])
        other = graph_dir / "other"
        altered = self.record.model_copy(update={"documents": [self.record.documents[0].model_copy(update={"text": "different"}), self.record.documents[1]]})
        write_json(other / "graph.json", altered.model_dump(mode="json"))
        with self.assertRaisesRegex(ConfigError, "different corpora"):
            qa.prepare(cfg.model_copy(update={"graphs": {"A0": graph_dir, "A4": other}}))
        question["supporting_facts"] = [["missing title", 0]]
        write_json(cfg.questions, [question])
        with self.assertRaisesRegex(ConfigError, "q1.*missing title"): qa.prepare(cfg)
        write_json(cfg.questions, [self.question()])
        (graph_dir / "metrics.json").write_text("[", encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "qa.graphs.A0"): qa.prepare(cfg)

    def test_reader_errors(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"yes"}}]}'
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(qa.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(qa.ask("http://127.0.0.1:9/v1", "m", [], 32, 12), "yes")
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, "http://127.0.0.1:9/v1/chat/completions")
            self.assertEqual(json.loads(request.data), {"model":"m","messages":[],"max_tokens":32,"temperature":0})
            for error, code in [(urllib.error.HTTPError("u",503,"miss",{},None), 5), (urllib.error.HTTPError("u",500,"fail",{},None), 6), (urllib.error.URLError("fail"),6)]:
                opener.open.side_effect = error
                with self.assertRaises(KgbError) as caught: qa.ask("http://127.0.0.1:9/v1", "m", [], 32, 12)
                self.assertEqual(caught.exception.code, code)
            opener.open.side_effect = None
            response.__enter__.return_value.read.return_value = b'{"choices":[]}'
            with self.assertRaises(KgbError) as caught: qa.ask("http://127.0.0.1:9/v1", "m", [], 32, 12)
            self.assertEqual(caught.exception.code, 6)

    def test_eval_no_context_and_row_order(self):
        questions = [self.question(), {**self.question(), "_id":"q2", "question":"nobody", "answer":"no"}]
        inputs = qa.QaInputs({"A0":self.record, "A1":self.record, "A4":self.record},
                             dict.fromkeys(["A0","A1","A4"]), dict.fromkeys(["A0","A1","A4"], "hash"), questions, self.record.documents)
        cfg = self.config.model_copy(update={"graphs":dict.fromkeys(["A0","A1","A4"], PROJECT_ROOT / "runs/_test/qa_unit")})
        stages = []
        write_jsonl(self.tmp / "llm_calls.jsonl", [
            {"stage":"qa.text", "cache_hit": True, "usage":{"prompt_tokens":7,"completion_tokens":2}, "seconds":0},
            {"stage":"qa.text", "cache_hit": False, "usage":{"prompt_tokens":3,"completion_tokens":1}, "seconds":1.2},
            {"stage":"other", "usage":{"prompt_tokens":999}, "seconds":999}])
        with patch.object(qa, "ask", return_value="yes") as ask:
            report = qa.eval_qa(cfg, inputs, "http://127.0.0.1:9/v1", "m", "lmstudio", 600, stages.append, self.tmp, self.encode)
        self.assertEqual(ask.call_count, 11)
        self.assertEqual([r["row"] for r in report["rows"]], ["text","graph@A0","graph@A1","graph@A4","hybrid@A0","hybrid@A1","hybrid@A4"])
        self.assertEqual(stages, ["qa." + r["row"] for r in report["rows"]])
        self.assertEqual(len(report["pairwise"]), 10)
        self.assertTrue(all(p["wins"]+p["ties"]+p["losses"] == 2 for p in report["pairwise"]))
        self.assertEqual(report["rows"][1]["no_context"], 1)
        self.assertEqual(report["rows"][1]["seeded"], 1)
        self.assertIsNone(report["rows"][0]["seeded"])
        self.assertEqual(report["rows"][0]["llm"], {"calls":2,"cache_hits":1,"cache_misses":0,
                         "prompt_tokens":10,"completion_tokens":3,"seconds":1.2})
        self.assertEqual(len(json.loads((self.tmp / "qa.json").read_text())["rows"]),7)


if __name__ == "__main__": unittest.main()

