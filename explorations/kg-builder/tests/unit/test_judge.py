"""In-process judge prompt, verdict, deduplication, and failure checks."""
from __future__ import annotations

import unittest
from urllib.error import URLError

from helpers import PROJECT_ROOT, SENTENCE_GROUNDING, clean_dir
from kgbuilder.build.refine.judge import (JudgeContext, evidence_window, judge_prompt, judge_prompt_v2,
                                         parse_verdict, risk_reasons, run_judge, statement_text)
from kgbuilder.core.config import KgbError, load_config
from kgbuilder.core.contracts import CanonicalTriple, Chunk, Document, Entity, Evidence, GraphRecord
from kgbuilder.core.text import read_jsonl


class JudgeTest(unittest.TestCase):
    def context(self, statements=None):
        statements = self.g.statements if statements is None else statements
        canonical = {cid: CanonicalTriple(candidate_id=cid, subject_id=s.subject_id, object_id=s.object_id,
                     predicate=s.predicate, predicate_source=s.predicate_source, open_predicate=s.predicate,
                     temporal_marker=None, time_iso=None, evidence=s.evidence_span, extractor_version="test")
                     for s in statements for cid in s.candidate_ids}
        return JudgeContext(canonical, {e.entity_id: e for e in self.g.entities},
                            {d.doc_id: d for d in self.g.documents}, {c.chunk_id: c for c in self.g.chunks})

    def test_v2_prompt_and_risk(self):
        content = "IBM Research works on artificial intelligence. IBM expanded its research division. IBM operates laboratories."
        doc = Document(doc_id="d2", text=content)
        chunk = Chunk(chunk_id="d2#c000", doc_id="d2", idx=0, char_start=0, char_end=len(content), text=content)
        start = content.index("IBM expanded")
        evidence = Evidence(doc_id="d2", chunk_id=chunk.chunk_id, char_start=start, char_end=content.index(" IBM operates"),
                            text="IBM expanded its research division.", grounding="exact")
        stmt = self.g.statements[2].model_copy(update={"predicate": "part_of", "evidence": [evidence], "evidence_span": evidence})
        base = self.context([stmt])
        entities = {eid: e.model_copy(update={"aliases": [], "name": "research division" if eid == stmt.object_id else e.name})
                    for eid, e in base.entities_by_id.items()}
        canonical = {cid: c.model_copy(update={"predicate_source": "schema", "open_predicate": "expanded"})
                     for cid, c in base.canonical_by_candidate.items()}
        ctx = JudgeContext(canonical, entities, {doc.doc_id: doc}, {chunk.chunk_id: chunk})
        names = {eid: e.name for eid, e in entities.items()}
        self.assertEqual(judge_prompt_v2(stmt, names, ctx),
                         "Instruction: Use only the input text, not outside knowledge. Is the following statement supported by the input text? "
                         "Answer yes or no.\nStatement: IBM part of research division\nInput: " + content + "\nOutput:")
        self.assertEqual(risk_reasons(stmt, ctx), ["canon_changed"])
        ctx = JudgeContext({cid: c.model_copy(update={"predicate_source": "trigger"}) for cid, c in canonical.items()},
                            entities, {doc.doc_id: doc.model_copy(update={"title": "Robert Florey"})}, ctx.chunks_by_id)
        self.assertEqual(risk_reasons(stmt, ctx), [])
        self.assertTrue(evidence_window(evidence, ctx).startswith("[Robert Florey] "))
        partial = stmt.model_copy(update={"evidence": [evidence.model_copy(update={"grounding": "partial"})]})
        entities[stmt.subject_id] = entities[stmt.subject_id].model_copy(update={"aliases": ["IBM alias"]})
        self.assertEqual(risk_reasons(partial, ctx), ["er_merged", "grounding"])
        self.assertEqual(statement_text(self.g.statements[0], self.names), "Alice works at Acme Labs (from 2021 until 2024)")

    def test_v2_soft_and_errors(self):
        ctx = self.context()
        cfg = self.cfg.model_copy(update={"judge": self.cfg.judge.model_copy(update={"version": "v2", "max_tokens": 32})})
        def run(ask, config=cfg):
            return run_judge(self.g.statements, self.names, config, "http://127.0.0.1:1/v1", self.root, ask=ask, context=ctx)
        kept, rejected, counts = run(lambda _: "No.")
        self.assertEqual(rejected, [])
        self.assertEqual((counts["judged"], counts["skipped"], counts["no"]), (1, 2, 1))
        self.assertEqual(kept[:2], self.g.statements[:2])
        self.assertEqual(kept[2].confidence, round(self.g.statements[2].confidence * .5, 3))
        self.assertEqual(kept[2].reasons, ["judge_no"])
        self.assertEqual(kept[2].status, "accepted")
        self.assertEqual(run(lambda _: "maybe")[0], self.g.statements)
        kept = run(lambda _: "Supported.")[0]
        self.assertEqual(kept[2].confidence, round(self.g.statements[2].confidence + (1 - self.g.statements[2].confidence) * .5, 3))
        all_cfg = cfg.model_copy(update={"judge": cfg.judge.model_copy(update={"scope": "all"})})
        def error(prompt):
            if "IBM" in prompt:
                raise URLError("test")
            return "yes"
        with self.assertRaises(KgbError) as caught:
            run(error, all_cfg)
        self.assertEqual(caught.exception.code, 6)
        with self.assertRaises(ValueError):
            run_judge([], {}, cfg, "http://127.0.0.1:1/v1", self.root)
        quiet = JudgeContext(ctx.canonical_by_candidate, {eid: e.model_copy(update={"aliases": []})
                              for eid, e in ctx.entities_by_id.items()}, ctx.documents_by_id, ctx.chunks_by_id)
        result = run_judge(self.g.statements, self.names, cfg, "http://127.0.0.1:1/v1", self.root,
                           ask=lambda _: self.fail("no risky facts"), context=quiet)
        self.assertEqual((result[0], result[2]["skipped"]), (self.g.statements, 3))

    def test_v1_reparse(self):
        kept, rejected, counts = self.run_judge(lambda _: "False.")
        self.assertEqual((kept, rejected, counts["unparsed"]), (self.g.statements, [], 3))
        cfg = self.cfg.model_copy(update={"judge": self.cfg.judge.model_copy(update={"version": "v1_reparse"})})
        kept, rejected, counts = run_judge(self.g.statements, self.names, cfg, "http://127.0.0.1:1/v1", self.root, ask=lambda _: "False.")
        self.assertEqual((kept, len(rejected), counts["no"]), ([], 3, 3))
        self.assertTrue(all(s.reasons == ["judge_no"] for s in rejected))

    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/judge" / self._testMethodName)
        self.g = GraphRecord.model_validate_json((PROJECT_ROOT / "tests/fixtures/graph_small.json").read_text(encoding="utf-8"))
        self.names = {e.entity_id: e.name for e in self.g.entities}
        self.cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", ablation="A5", sets=SENTENCE_GROUNDING)

    def run_judge(self, ask, statements=None):
        return run_judge(self.g.statements if statements is None else statements, self.names, self.cfg,
                         "http://127.0.0.1:1/v1", self.root, ask=ask)

    def test_prompts_and_verdicts(self):
        self.assertEqual(judge_prompt(self.g.statements[2], self.names), "Instruction: Is this true: IBM operates Acme Labs?\nInput: IBM operates Acme Labs.\nOutput:")
        self.assertTrue(judge_prompt(self.g.statements[0], self.names).startswith("Instruction: Is this true: Alice works at Acme Labs?\nInput: 2021: Alice joined Acme Labs."))
        stmt = self.g.statements[0].model_copy(update={"predicate": "birthPlace"})
        self.assertTrue(judge_prompt(stmt, {"e1": "Nie_Haisheng", "e2": "Zaoyang"}).startswith("Instruction: Is this true: Nie Haisheng birth place Zaoyang?"))
        for value, expected in [("No, this is not true.", "no"), ("Yes, it is true.", "yes"), ("  YES", "yes"),
                                ("Not sure, yes", "yes"), ("I don't know", None), ("Nothing", None), ("maybe", None)]:
            self.assertEqual(parse_verdict(value), expected)
        ev = self.g.statements[0].evidence[0]
        stmt = stmt.model_copy(update={"evidence": [ev, ev, *[ev.model_copy(update={"text": str(i)}) for i in range(4)]]})
        self.assertEqual(judge_prompt(stmt, self.names).split("Input: ")[1].split("\nOutput:")[0], ev.text + "\n0\n1")

    def test_rejections(self):
        kept, rejected, counts = self.run_judge(lambda p: "No, this is not true." if "operates" in p else "Yes, this is true.")
        self.assertEqual([s.statement_id for s in kept], ["s1", "s2"])
        self.assertEqual([s.statement_id for s in rejected], ["s3"])
        self.assertEqual(rejected[0].reasons, ["judge_no"])
        self.assertEqual(rejected[0].status, "rejected")
        self.assertEqual(counts, {"judged": 3, "yes": 2, "no": 1, "unparsed": 0, "errors": 0})
        self.assertEqual(len(read_jsonl(self.root / "judge.jsonl")), 3)
        self.assertEqual(self.g.statements[2].status, "accepted")

    def test_unparsed_and_duplicates(self):
        kept, rejected, counts = self.run_judge(lambda _: "maybe")
        self.assertEqual((len(kept), rejected, counts["unparsed"]), (3, [], 3))
        calls = []
        def fake(prompt):
            calls.append(prompt)
            return "yes"
        one = self.g.statements[0]
        kept, _, counts = self.run_judge(fake, [one.model_copy(update={"statement_id": "z"}), one])
        self.assertEqual(len(calls), 1)
        self.assertEqual([s.statement_id for s in kept], ["s1", "z"])
        self.assertEqual(counts["yes"], 2)

    def test_errors_and_empty(self):
        for error in [URLError("offline"), KeyError("choices")]:
            def ask(prompt):
                if "operates" in prompt:
                    raise error
                return "yes"
            with self.assertRaises(KgbError) as caught:
                self.run_judge(ask)
            self.assertEqual(caught.exception.code, 6)
            self.assertEqual(sum(r["error"] is not None for r in read_jsonl(self.root / "judge.jsonl")), 1)
        self.assertEqual(self.run_judge(lambda _: "yes")[2]["errors"], 0)
        def boom(_):
            self.fail("empty judge must not call")
        self.assertEqual(self.run_judge(boom, []), ([], [], {"judged": 0, "yes": 0, "no": 0, "unparsed": 0, "errors": 0}))
        self.assertEqual((self.root / "judge.jsonl").read_bytes(), b"")
