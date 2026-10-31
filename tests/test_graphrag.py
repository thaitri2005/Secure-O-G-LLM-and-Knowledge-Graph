"""Track B baseline pieces without any model call: client guard, cache and ledger; BM25; fusion; scoring."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from graphrag.baseline import fact_sheet, render
from graphrag.client import Endpoint, ModelClient, PrivateDataError
from graphrag.data import Chunk, load_questions
from graphrag.ontology import glossary, guidance, load as load_k2
from graphrag.tables import column, extract as extract_tables
from graphrag.validate import validate
from graphrag.retrieval import BM25, Fusion, WellRouter, well_names
from graphrag.citations import resolve
from graphrag.scoring import normalize, score_answer, same_value

HOSTED = Endpoint("openrouter", "https://example.invalid/v1", True, None, 1.0, 2.0)
LOCAL = Endpoint("local-llama", "http://127.0.0.1:9/v1", False)


def reply(content, prompt=100, completion=20, cost=None):
    usage = {"prompt_tokens": prompt, "completion_tokens": completion}
    if cost is not None:
        usage["cost"] = cost
    request = httpx.Request("POST", "https://example.invalid")
    return httpx.Response(200, request=request, json={"model": "m", "usage": usage,
                                                      "choices": [{"message": {"content": content}}]})


class ClientTests(unittest.TestCase):
    def test_private_data_never_reaches_a_hosted_endpoint(self):
        client = ModelClient(HOSTED, "m", cache_dir=None)
        with patch("graphrag.client.httpx.post") as post:
            with self.assertRaises(PrivateDataError):
                client.chat([{"role": "user", "content": "x"}], data_class="private")
            post.assert_not_called()

    def test_local_endpoint_accepts_private_data(self):
        client = ModelClient(LOCAL, "m", cache_dir=None)
        with patch("graphrag.client.httpx.post", return_value=reply("hi")):
            self.assertEqual(client.chat([{"role": "user", "content": "x"}], data_class="private").content, "hi")

    def test_cost_from_prices_and_cache_hit_is_free(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = ModelClient(HOSTED, "m", cache_dir=Path(temporary))
            messages = [{"role": "user", "content": "x"}]
            with patch("graphrag.client.httpx.post", return_value=reply('{"a": 1}', 1_000_000, 500_000)) as post:
                first = client.chat(messages, schema={"type": "object"})
                second = client.chat(messages, schema={"type": "object"})
            self.assertEqual(post.call_count, 1)
            self.assertEqual(first.cost_usd, 2.0)
            self.assertEqual((second.cached, second.cost_usd, second.parsed), (True, 0.0, {"a": 1}))
            summary = client.ledger.summary()
            self.assertEqual((summary["calls"], summary["cached_calls"], summary["cost_usd"]), (2, 1, 2.0))

    def test_reported_cost_wins_and_invalid_json_is_counted(self):
        client = ModelClient(HOSTED, "m", cache_dir=None)
        with patch("graphrag.client.httpx.post", return_value=reply("not json", cost=0.003)):
            call = client.chat([{"role": "user", "content": "x"}], schema={"type": "object"})
        self.assertIsNone(call.parsed)
        self.assertEqual((call.cost_usd, client.ledger.invalid_json), (0.003, 1))

    def test_embeddings_keep_input_order_and_are_counted(self):
        client = ModelClient(LOCAL, "e", cache_dir=None)
        request = httpx.Request("POST", "http://127.0.0.1:9")
        response = httpx.Response(200, request=request, json={
            "usage": {"prompt_tokens": 7},
            "data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]})
        with patch("graphrag.client.httpx.post", return_value=response):
            self.assertEqual(client.embed(["a", "b"]), [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual((client.ledger.calls, client.ledger.prompt_tokens), (1, 7))

    def test_schema_is_sent_as_response_format(self):
        client = ModelClient(LOCAL, "m", cache_dir=None)
        with patch("graphrag.client.httpx.post", return_value=reply("{}")) as post:
            client.chat([{"role": "user", "content": "x"}], schema={"type": "object"})
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["response_format"]["json_schema"]["schema"], {"type": "object"})
        self.assertNotIn("usage", body)


def chunk(n, text, section=None):
    return Chunk(f"d#c{n:04d}", "d", 1, "text", section, text)


class RetrievalTests(unittest.TestCase):
    chunks = [chunk(0, "The well was drilled to a total depth of 1,955 feet."),
              chunk(1, "Mud weight and rheology were stable."),
              chunk(2, "Rig released on 6 September.", section="Drilling Summary")]

    def test_bm25_ranks_the_matching_chunk_first(self):
        self.assertEqual(BM25(self.chunks).search("What total depth was drilled?", 1)[0][0], "d#c0000")

    def test_section_heading_is_searchable(self):
        self.assertEqual(BM25(self.chunks).search("drilling summary", 1)[0][0], "d#c0002")

    def test_fusion_combines_rankings(self):
        bm25 = BM25(self.chunks)
        fused = Fusion([bm25, bm25]).search("mud weight", 2)
        self.assertEqual(fused[0][0], "d#c0001")

    def test_well_names_skip_casing_sizes(self):
        self.assertEqual(well_names("AK-3 and 56-32 near TG-2; 4-1/2 inch casing, 9-5/8 in."), {"AK-3", "56-32", "TG-2"})

    def test_well_router_keeps_only_documents_naming_the_well(self):
        pool = [Chunk("a#c0000", "a", 1, "text", None, "Well AK-3 reached total depth of 1,955 ft."),
                Chunk("a#c0001", "a", 2, "text", None, "Total depth summary table."),
                Chunk("b#c0000", "b", 1, "text", None, "Well 68-32 total depth 978 ft, total depth reached.")]
        router = WellRouter(BM25(pool), pool)
        self.assertEqual(router.documents("What total depth did AK-3 reach?"), ["a"])
        self.assertTrue(all(cid.startswith("a#") for cid, _ in router.search("What total depth did AK-3 reach?", 3)))
        self.assertEqual(len(router.search("What total depth was reached?", 3)), 3)


class ScoringTests(unittest.TestCase):
    depth = {"id": "g01", "value": 1955}
    casing = {"id": "g17", "value": 221.7, "alternatives": [220]}

    def test_values_match_like_the_prototype(self):
        self.assertTrue(same_value("1,955 ft", 1955))
        self.assertTrue(same_value("2016-08-18", "2016-08-18"))
        self.assertFalse(same_value("August 18, 2016", "2016-08-18"))
        self.assertTrue(score_answer({}, [self.casing], "answered", ["220"])["correct"])

    def test_extra_wrong_value_fails(self):
        self.assertFalse(score_answer({}, [self.depth], "answered", ["1955", "1700"])["correct"])

    def test_no_expected_fact_requires_no_answer(self):
        self.assertTrue(score_answer({}, [], "not_stated", [])["correct"])
        self.assertFalse(score_answer({}, [], "answered", ["42"])["correct"])

    def test_dates_and_numbers_are_normalized_in_code(self):
        self.assertEqual(normalize("09-Mar-19"), "2019-03-09")
        self.assertEqual(normalize("18 August 2016"), "2016-08-18")
        self.assertEqual(normalize("August 18th, 2016"), "2016-08-18")
        self.assertEqual(normalize("1,955 ft"), "1955 ft")
        self.assertEqual(normalize("12-1/4"), "12-1/4")


class CitationTests(unittest.TestCase):
    texts = {"d#c0001": "Mud weight was 9.2 ppg.", "d#c0002": "Total depth 1,955 ft MD was reached."}
    hits = ["d#c0001", "d#c0002"]

    def test_correct_citation_is_kept(self):
        answer = {"value": "1955", "chunk": "c0002", "quote": "Total depth 1,955 ft"}
        self.assertEqual(resolve(answer, self.hits, self.texts, "d"), ("d#c0002", "model"))

    def test_wrong_chunk_is_repaired_from_the_quote_or_value(self):
        by_quote = {"value": "1955", "chunk": "c0001", "quote": "1,955 ft MD"}
        self.assertEqual(resolve(by_quote, self.hits, self.texts, "d"), ("d#c0002", "by_quote"))
        by_value = {"value": "9.2", "chunk": "c0099", "quote": "invented"}
        self.assertEqual(resolve(by_value, self.hits, self.texts, "d"), ("d#c0001", "by_value"))

    def test_thousands_separator_does_not_break_support(self):
        answer = {"value": "1955", "chunk": "c0099", "quote": "reached TD at 1955 feet"}
        self.assertEqual(resolve(answer, self.hits, self.texts, "d"), ("d#c0002", "by_value"))

    def test_unsupported_answer_gets_no_citation(self):
        answer = {"value": "3000", "chunk": "c0002", "quote": "3000 ft"}
        self.assertEqual(resolve(answer, self.hits, self.texts, "d"), (None, "unsupported"))

class OntologyTests(unittest.TestCase):
    def test_glossary_merges_expansions_and_flags_merged_cells(self):
        table = {"table_id": "d#t1", "cells": [
            {"r": 0, "c": 0, "text": "Abbreviation or Acronyms"}, {"r": 0, "c": 1, "text": "Description"},
            {"r": 1, "c": 0, "text": "TD"}, {"r": 1, "c": 1, "text": "Total Depth"},
            {"r": 2, "c": 0, "text": "JSA jt"}, {"r": 2, "c": 1, "text": "job safety analysis Joint"}]}
        other = dict(table, table_id="d#t2", cells=[{"r": 0, "c": 0, "text": "TD"}, {"r": 0, "c": 1, "text": "total depth"}])
        k2 = {"sources": {"glossary_tables": ["d#t1", "d#t2"], "unit_tables": []}}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tables.jsonl"
            path.write_text("\n".join(json.dumps(t) for t in (table, other)), encoding="utf-8")
            entries = {e["term"]: e for e in glossary(k2, path)}
        self.assertEqual(entries["TD"]["expansions"], ["Total Depth"])
        self.assertEqual(entries["TD"]["tables"], ["d#t1", "d#t2"])
        self.assertIn("check", entries["JSA jt"])

    def test_k2_renders_as_lightrag_guidance(self):
        text = guidance(load_k2())
        self.assertIn("- Well:", text)
        self.assertIn("Well MONITORS Well", text)


class FactSheetTests(unittest.TestCase):
    def test_facts_group_by_well_with_well_level_facts_first(self):
        facts = [{"chunk": "d#c1", "well": "Well AK-3", "property": "inclination", "qualifier": "actual",
                  "context": {"depth_ft": 600}, "value": 1},
                 {"chunk": "d#c2", "well": "AK-3", "property": "total_depth", "qualifier": "actual",
                  "context": None, "value": 1955}]
        sheet = fact_sheet(facts)
        self.assertEqual(list(sheet), ["AK-3"])
        self.assertLess(sheet["AK-3"].index("total_depth"), sheet["AK-3"].index("inclination"))
        self.assertIn("[d#c2]", sheet["AK-3"])


class ValidateTests(unittest.TestCase):
    texts = {"a#c1": "Well AK-3 was drilled to 1,955 ft. Spud on 18 August 2016.",
             "a#c2": "AK-3 reached 1,955 feet.",
             "a#c3": "Total depth 1,900 ft for AK-3.",
             "b#c1": "Well 68-32 daily report. Days: 0"}

    def fact(self, chunk, well, value, prop="total_depth"):
        return {"chunk": chunk, "well": well, "property": prop, "qualifier": "actual", "context": None, "value": value}

    def test_value_must_be_written_in_its_chunk(self):
        kept, rejected = validate([self.fact("a#c1", "AK-3", 2000.0)], self.texts)
        self.assertEqual((kept, rejected), ([], {"value not in its chunk": 1}))

    def test_float_and_date_forms_are_found(self):
        kept, _ = validate([self.fact("a#c1", "Akutan Well AK-3", 1955.0),
                            self.fact("a#c1", "AK-3", "2016-08-18", "spud_date")], self.texts)
        self.assertEqual([f["value"] for f in kept], ["1955", "2016-08-18"])

    def test_well_must_be_single_and_named_in_its_document_and_zero_is_empty(self):
        _, rejected = validate([self.fact("a#c1", "Bows", 1955), self.fact("b#c1", "AK-3", 1955),
                                self.fact("b#c1", "68-32", 0, "drilling_days")], self.texts)
        self.assertEqual(rejected, {"no single well name": 1, "well not named in its document": 1, "zero value": 1})

    def test_majority_wins_and_ties_drop_the_key(self):
        kept, rejected = validate([self.fact("a#c1", "AK-3", 1955), self.fact("a#c2", "AK-3", 1955),
                                   self.fact("a#c3", "AK-3", 1900)], self.texts)
        self.assertEqual([f["value"] for f in kept], ["1955"])
        self.assertEqual(rejected, {"contradicted, outvoted": 1})
        kept, rejected = validate([self.fact("a#c1", "AK-3", 1955), self.fact("a#c3", "AK-3", 1900)], self.texts)
        self.assertEqual((kept, rejected), ([], {"contradicted, tie": 2}))


class TableMappingTests(unittest.TestCase):
    def test_headers_match_whole_words_only(self):
        heads = ["hole (inches)", "casing (inches)", "depth (feet)"]
        self.assertIsNone(column(heads, "inclination|inc"))
        self.assertEqual(column(heads, "depth"), 2)
        self.assertEqual(column(["measured depth", "inc (deg)"], "inclination|inc"), 1)

    def test_casing_table_rows_become_planned_facts_with_their_chunk(self):
        cells = [{"r": r, "c": c, "text": t} for r, row in enumerate(
            [["Hole (inches)", "Casing (inches)", "Depth (feet)"], ["10-3/4", "8-5/8 (8\" line pipe)", "~ 40"],
             ["7-1/2", "5-1/2", "~ 220"]]) for c, t in enumerate(row)]
        table = {"table_id": "d#t1", "doc_id": "d", "header_rows": 1, "rendered_header_rows": 1, "cells": cells}
        chunk_ = Chunk("d#c0001", "d", 1, "table", None, "Table 1: Planned XY-1 casing. | Hole | Casing | Depth |",
                       "d#t1", 1, 2)
        named = Chunk("d#c0000", "d", 1, "text", None, "Well XY-1 was drilled.")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tables.jsonl"
            path.write_text(json.dumps(table), encoding="utf-8")
            with patch("graphrag.tables.TABLES", path):
                facts = extract_tables([named, chunk_], load_k2())
        self.assertEqual([(f["well"], f["qualifier"], f["context"]["casing_size_in"], f["value"], f["chunk"]) for f in facts],
                         [("XY-1", "planned", "8-5/8", "40", "d#c0001"), ("XY-1", "planned", "5-1/2", "220", "d#c0001")])


class QuestionSetTests(unittest.TestCase):
    def test_probe_questions_have_gold_facts_with_full_chunk_ids(self):
        questions, gold = load_questions("probe")
        self.assertTrue(all(g in gold for q in questions for g in q["gold"]))
        self.assertTrue(all("#" in c for fact in gold.values() for c in fact["chunks"]))


class FactTests(unittest.TestCase):
    def test_fact_renders_with_qualifier_and_context(self):
        fact = {"well": "AK-3", "property": "casing_depth", "qualifier": "planned", "value": 220,
                "context": {"casing_size_in": "5-1/2"}}
        self.assertEqual(render(fact), "AK-3 casing_depth (planned) at casing_size_in 5-1/2 = 220")


@unittest.skipUnless(importlib.util.find_spec("neo4j_graphrag"), "needs requirements-graphrag.lock.txt")
class Neo4jKgTests(unittest.TestCase):
    def setUp(self):
        from graphrag import neo4j_kg
        self.kg = neo4j_kg
        self.profile = json.loads(neo4j_kg.PROFILE.read_text(encoding="utf-8"))

    def test_profile_becomes_a_pruning_schema(self):
        schema = self.kg.schema_from_profile(self.profile)
        labels = [n["label"] for n in schema["node_types"]]
        self.assertEqual(labels[0], "Well")
        self.assertIn("Inclination", labels)
        well = [p["name"] for p in schema["node_types"][0]["properties"]]
        self.assertIn("planned_total_depth", well)
        self.assertNotIn("inclination", well)
        self.assertIn(("Well", "HAS_INCLINATION", "Inclination"), schema["patterns"])
        self.assertFalse(schema["additional_node_types"])

    def test_well_names_and_casing_sizes_compare_loosely(self):
        self.assertEqual(self.kg.well_key("Akutan Well AK-3", self.profile), self.kg.well_key("AK-3", self.profile))
        self.assertEqual(self.kg.size("8-5/8"), self.kg.size("8.625"))
        self.assertIsNone(self.kg.size("blank"))

    def test_extraction_score_counts_wrong_values_where_gold_has_the_key(self):
        facts = [{"chunk": "c", "well": "AK-3", "property": "total_depth", "qualifier": "actual", "value": 1955,
                  "context": None},
                 {"chunk": "c", "well": "AK-3", "property": "total_depth", "qualifier": "planned", "value": 1800,
                  "context": None}]
        score = self.kg.score_extraction(facts, self.profile)
        self.assertEqual((score["gold_found"], score["facts_with_gold_key"], score["right_where_keyed"]), (1, 2, 1))


if __name__ == "__main__":
    unittest.main()
