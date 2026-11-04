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
from graphrag.k4 import SCHEMA as K4_SCHEMA, records as k4_records
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


class K4Tests(unittest.TestCase):
    def test_records_from_a_run_match_the_schema(self):
        import jsonschema
        run = {"question_set": "prototype", "model": "qwen3-8b", "endpoint": "local-llama", "retriever": "wells:bm25",
               "k": 5, "cost": {"models": ["local-llama:qwen3-8b"]},
               "rows": [{"id": "q01", "status": "answered", "values": ["1955"], "units": ["ft"], "correct": True,
                         "citations": [{"chunk": "gdr882_ak3_eowr#c0010", "how": "model"}],
                         "prompt_tokens": 1400, "completion_tokens": 80, "seconds": 1.2}]}
        with tempfile.TemporaryDirectory() as temporary:
            Path(temporary, "r.json").write_text(json.dumps(run), encoding="utf-8")
            with patch("graphrag.k4.RESULTS", Path(temporary)):
                rows = k4_records("r")
        schema = json.loads(K4_SCHEMA.read_text(encoding="utf-8"))
        jsonschema.validate(rows[0], schema)
        self.assertEqual(rows[0]["answers"], [{"value": "1955", "unit": "ft"}])
        self.assertEqual(rows[0]["question"], "What total depth did well AK-3 reach?")


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


class SimulatedSetTests(unittest.TestCase):
    def test_gold_values_are_written_in_their_chunks(self):
        from graphrag.data import load_chunks, load_questions

        text = {c.id: c.text.replace(",", "") for c in load_chunks()}
        questions, gold = load_questions("simulated")
        self.assertEqual({g for q in questions for g in q["gold"]}, set(gold))
        for fact in gold.values():
            for chunk in fact["chunks"]:
                self.assertIn(chunk, text)
                if fact.get("derived"):
                    continue
                values = [str(v).replace(",", "") for v in [fact["value"], *fact.get("alternatives", [])]]
                values += ["9 March 2021"] if fact["value"] == "2021-03-09" else []
                values += [v.rstrip("0").rstrip(".") for v in values if "." in v]
                self.assertTrue(any(v in text[chunk] for v in values), (fact["id"], chunk))


class TableMappingFixTests(unittest.TestCase):
    def test_section_row_is_not_a_header(self):
        from graphrag.tables import header_count

        rows = [["Survey", "Meas."], ["Type", "Depth (ft)", "Inc. (deg)"], ["Wellbore:", "Original Wellbore"], ["MSS", "500", "0.9"]]
        self.assertEqual(header_count(rows), 2)

    def test_decimal_casing_size_is_kept_whole(self):
        from graphrag.tables import SIZE, first

        self.assertEqual(first(SIZE, "9.625"), "9.625")
        self.assertEqual(first(SIZE, "5-1/2"), "5-1/2")


class CoverageMappingTests(unittest.TestCase):
    def extract(self, cells):
        from graphrag.data import Chunk
        from graphrag.ontology import load
        from graphrag.tables import extract

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tables.jsonl"
            cell_list = [{"r": r, "c": c, "text": t} for r, row in enumerate(cells) for c, t in enumerate(row)]
            path.write_text(json.dumps({"table_id": "d#t1", "doc_id": "d", "cells": cell_list}), encoding="utf-8")
            chunk = Chunk("d#c1", "d", 1, "table", None, "XY-1 table", "d#t1", 0, len(cells))
            return extract([chunk], load(), path)

    def test_specification_column_gives_weight_and_grade(self):
        facts = self.extract([["Section", "Casing Size (in.)", "Specifications", "Actual Depth (ft.)"],
                              ["Production", "5-1/2", "17 ppf, L-80, BTC", "9,135"]])
        got = {f["property"]: (f["value"], f["context"]) for f in facts if f["property"] != "casing_depth"}
        self.assertEqual(got, {"casing_weight": ("17", {"casing_size_in": "5-1/2"}),
                               "casing_grade": ("L-80", {"casing_size_in": "5-1/2"})})

    def test_own_columns_give_weight_and_grade(self):
        facts = self.extract([["Hole (inches)", "Casing (inches)", "Weight (ppf)", "Grade", "Depth (feet)"],
                              ["7-1/2", "5-1/2", "15.5", "K55", "221.7"]])
        got = {f["property"]: f["value"] for f in facts if f["property"] != "casing_depth"}
        self.assertEqual(got, {"casing_weight": "15.5", "casing_grade": "K55"})

    def test_key_value_rows(self):
        facts = self.extract([["Field:", "FORGE UTAH"], ["Drilling Contractor (PM):", "Frontier"], ["Drilling Rig:", "Rig-16"]])
        self.assertEqual({f["property"]: f["value"] for f in facts}, {"drilling_contractor": "Frontier", "rig": "Rig-16"})


class EventGraphTests(unittest.TestCase):
    def events(self):
        from graphrag.events import Event

        return [Event("2016-08-20", "0:00", "9:30", 9.5, 100, "DRIL", "", ["a"]),
                Event("2016-08-20", "9:30", "10:00", 0.5, 100, "SURV", "", ["b"]),
                Event("2016-08-20", "17:00", "18:00", 1.0, 176, "STUCK", "", ["c"], "KICK"),
                Event("2016-08-21", "0:00", "0:00", 24.0, 176, "KICK", "", ["d"], "KICK"),
                Event("2016-08-22", "0:00", "6:00", 6.0, 300, "DRIL", "", ["e"])]

    def plan(self, operation, **fields):
        return {"operation": operation, "well": "AK-3", **fields}

    def test_totals_filters_and_empty_results(self):
        from graphrag.events import run_plan

        self.assertIn("= 15.5 (2 events on 2 dates)", run_plan(self.plan("total_hours", code="dril"), self.events())[0])
        self.assertIn("= 25 ", run_plan(self.plan("total_hours", non_productive=True), self.events())[0])
        self.assertIn("= 9.5 ", run_plan(self.plan("total_hours", code="DRIL", date_to="2016-08-20", date_from="2016-08-20"), self.events())[0])
        self.assertEqual(run_plan(self.plan("total_hours", code="SIDETRACK"), self.events()), ("", []))
        self.assertEqual(run_plan({"operation": "total_hours", "well": "56-32", "code": "DRIL"}, self.events()), ("", []))
        self.assertEqual(run_plan(self.plan("total_hours", non_productive=True, date_from="2017-01-01"), self.events()), ("", []))

    def test_non_productive_plans_with_a_stray_code(self):
        from graphrag.events import run_plan

        self.assertIn("= 25 ", run_plan(self.plan("total_hours", code="non_productive", non_productive=True), self.events())[0])
        self.assertIn("= 25 ", run_plan(self.plan("total_hours", code="KICK", npt_code="KICK"), self.events())[0])
        self.assertIn("= 1 ", run_plan(self.plan("total_hours", code="STUCK", non_productive=True), self.events())[0])
        self.assertEqual(run_plan(self.plan("total_hours", code="non_productive"), self.events()), ("", []))

    def test_days_dates_and_groups(self):
        from graphrag.events import run_plan

        self.assertIn("= 2", run_plan(self.plan("count_days", code="DRIL"), self.events())[0])
        self.assertIn("at least 24 hours = 1", run_plan(self.plan("count_days", non_productive=True, min_hours_per_day=24), self.events())[0])
        self.assertIn("2016-08-20, 2016-08-22", run_plan(self.plan("list_dates", code="DRIL"), self.events())[0])
        self.assertIn("= 2016-08-22", run_plan(self.plan("last_date", code="DRIL"), self.events())[0])
        self.assertIn("= KICK (24 hours)", run_plan(self.plan("top_group", group_by="code"), self.events())[0])

    def test_depth_ignores_code_filters_and_rests_on_its_events(self):
        from graphrag.events import run_plan

        self.assertIn("= 176 ft", run_plan(self.plan("depth_on_date", date_from="2016-08-21", code="DRIL"), self.events())[0])
        self.assertIn("rose by 124 ft", run_plan(self.plan("depth_gain", date_from="2016-08-21", date_to="2016-08-22"), self.events())[0])
        result, rows = run_plan(self.plan("first_date_depth_at_least", depth_ft=150), self.events())
        self.assertIn("= 2016-08-20", result)
        self.assertEqual(rows[0].chunks, ["c"])

    def test_rows_merge_across_attachments_and_join_the_non_productive_report(self):
        from graphrag.data import Chunk
        from graphrag.events import build_events

        def cells(rows):
            return [{"r": r, "c": c, "text": t} for r, row in enumerate(rows) for c, t in enumerate(row)]

        head = ["From", "To", "Elapsed", "End MD(ft)", "Code", "Operations Description"]
        chunks = [Chunk("a#c1", "a", 1, "text", "Report For 20-Aug-16", "Well AK-3"),
                  Chunk("a#c2", "a", 1, "table", None, "t", "a#t1", 0, 2),
                  Chunk("b#c1", "b", 1, "text", None, "Report For 20-Aug-16 Well AK-3"),
                  Chunk("b#c2", "b", 1, "table", None, "t", "b#t1", 0, 2),
                  Chunk("n#c1", "n", 1, "table", None, "t", "n#t1", 0, 2)]
        tables = [{"table_id": "a#t1", "doc_id": "a", "cells": cells([head, ["0:00", "1:00", "1.00", "10", "DRIL", "x"]])},
                  {"table_id": "b#t1", "doc_id": "b", "cells": cells([head, ["0:00", "1:00", "1.00", "10", "DRIL", "x"]])},
                  {"table_id": "n#t1", "doc_id": "n", "cells": cells([["NPT Code", "Rpt No", "Report Date", "Time From", "Time To", "Hours", "End MD", "Ops Code", "Activity"],
                                                                     ["KICK", "9", "20-Aug-16", "0:00", "1:00", "1.00", "10", "DRIL", "x"],
                                                                     ["WAIT", "9", "20-Aug-16", "1:00", "2:00", "1.00", "10", "WOW", "y"]])}]
        events, stats = build_events(chunks, tables)
        self.assertEqual(len(events), 2)
        self.assertEqual((events[0].npt_code, events[0].chunks), ("KICK", ["a#c2", "b#c2", "n#c1"]))
        self.assertEqual((events[1].code, events[1].npt_code), ("WOW", "WAIT"))
        self.assertEqual(stats["added from the non-productive report"], 1)


class DateRouterTests(unittest.TestCase):
    def chunks(self):
        from graphrag.data import Chunk

        return [Chunk("d#c1", "d", 1, "text", "Report For 28-Aug-16", "Well AK-3 mud 8.6"),
                Chunk("d#c2", "d", 2, "text", None, "Well AK-3 mud 8.6 continued"),
                Chunk("d#c3", "d", 3, "text", None, "Report For 29-Aug-16 Well AK-3 mud 8.6"),
                Chunk("n#c1", "n", 1, "text", None, "Report No: 8 Report For 29-Aug-16"),
                Chunk("g#c1", "g", 1, "text", None, "Report No: 8 Graphical Summary, Printed: 20-Sep-16")]

    def test_continuation_pages_inherit_the_date(self):
        from graphrag.retrieval import page_dates

        self.assertEqual(page_dates(self.chunks()), {("d", 1): "2016-08-28", ("d", 2): "2016-08-28", ("d", 3): "2016-08-29",
                                                     ("n", 1): "2016-08-29", ("g", 1): "2016-08-29"})

    def test_filters_only_on_dates_a_report_has(self):
        from graphrag.retrieval import BM25, DateRouter

        router = DateRouter(BM25(self.chunks()), self.chunks())
        self.assertEqual({c for c, _ in router.search("AK-3 mud on 28 August 2016", 5)}, {"d#c1", "d#c2"})
        everything = {c.id for c in self.chunks()}
        self.assertEqual({c for c, _ in router.search("AK-3 mud on 1 January 2020", 9)}, everything)
        self.assertEqual({c for c, _ in router.search("AK-3 mud", 9)}, everything)


class UnseenReportMappingTests(unittest.TestCase):
    def extract(self, cells, text="Well TNT-GT-01 report"):
        from graphrag.data import Chunk
        from graphrag.ontology import load
        from graphrag.tables import extract

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tables.jsonl"
            cell_list = [{"r": r, "c": c, "text": t} for r, row in enumerate(cells) for c, t in enumerate(row)]
            path.write_text(json.dumps({"table_id": "d#t1", "doc_id": "d", "cells": cell_list}), encoding="utf-8")
            chunk = Chunk("d#c1", "d", 1, "table", None, text, "d#t1", 0, len(cells))
            return extract([chunk], load(), path)

    def test_well_names_with_several_parts(self):
        from graphrag.retrieval import well_names

        self.assertEqual(well_names("Well TNT-GT-01 and HON-GT-01-S2, AK-3 and 56-32, J-55"), {"TNT-GT-01", "HON-GT-01-S2", "AK-3", "56-32", "J-55"})

    def test_sizes_in_one_form(self):
        from graphrag.tables import casing_size_text

        self.assertEqual(casing_size_text('13 ⅜" Casing'), "13-3/8")
        self.assertEqual(casing_size_text("13 3/8 casing"), "13-3/8")
        self.assertEqual(casing_size_text('9-⅝"'), "9-5/8")
        self.assertEqual(casing_size_text('24" Conductor'), "24")

    def test_item_tables_take_the_deepest_bottom_and_label_metres(self):
        facts = self.extract([["Item", "Top (m MDRT)", "Bottom (m MDRT)", "Weight", "Grade"],
                              ['13 ⅜" Casing', "0", "1275", "68 ppf", "K55"],
                              ['9 ⅝" mixed string liner', "1218", "2383", "51.9 ppf", "L80"],
                              ["2393", "2821", "47 ppf", "13Cr L80"],
                              ["2821", "2857", "47 ppf", "L80"],
                              ['8 ½" Hole', "0", "3000", "", ""]])
        got = {f["context"]["casing_size_in"]: (f["value"], f["unit"]) for f in facts if f["property"] == "casing_depth"}
        self.assertEqual(got, {"13-3/8": ("1275", "m"), "9-5/8": ("2857", "m")})
        self.assertEqual({f["well"] for f in facts}, {"TNT-GT-01"})

    def test_item_tables_in_feet_have_no_unit_label(self):
        facts = self.extract([["Item", "MD", "Comments"], ['7" Liner', "4,000", "ok"]], "Well AK-3")
        self.assertEqual([(f["value"], f.get("unit")) for f in facts], [("4000", None)])

    def test_merged_survey_rows_split_only_when_they_pair_up(self):
        from graphrag.tables import paired_numbers

        self.assertEqual(paired_numbers("114.20 125.50", "0.20 0.10"), [("114.20", "0.20"), ("125.50", "0.10")])
        self.assertEqual(paired_numbers("1834.10 1847.20", "30.30"), [])
        self.assertEqual(paired_numbers("m", "° 30.20"), [])
        self.assertEqual(paired_numbers("1,100", "1"), [("1100", "1")])

    def test_metre_surveys_are_labelled(self):
        facts = self.extract([["MD", "Inc", "Azi"], ["m", "°", "°"], ["114.20 125.50", "0.20 0.10", "301 327"], ["bad", "1.0", "2"]])
        self.assertEqual([(f["context"], f["value"]) for f in facts],
                         [({"depth_m": "114.20"}, "0.20"), ({"depth_m": "125.50"}, "0.10")])


class SecondRoundMappingTests(unittest.TestCase):
    def test_unit_row_merged_into_data_still_means_metres(self):
        facts = UnseenReportMappingTests().extract([["MD", "Inc"], ["m", "° 30.20"], ["1834.10", "30.30"], ["1847.20", "30.40"]])
        self.assertEqual([f["context"] for f in facts], [{"depth_m": "1834.10"}, {"depth_m": "1847.20"}])

    def test_shifted_columns_are_dropped(self):
        from graphrag.tables import steady_readings

        readings = [(i, str(1800 + 10 * i), "30.0") for i in range(8)] + [(8, "1880", "1.46"), (9, "32.30", "30.1")]
        kept = steady_readings(readings, 10)
        self.assertEqual(len(kept), 8)
        self.assertNotIn("1.46", [r[2] for r in kept])
        self.assertNotIn("32.30", [r[1] for r in kept])

    def test_cement_tables_give_no_casing_depth(self):
        facts = UnseenReportMappingTests().extract([["Item", "TOC (m MDRT)", "Lead Slurry Volume"], ['13 ⅜" Casing', "135", "97"]])
        self.assertEqual(facts, [])

    def test_strict_check_reads_every_way_of_writing_a_size(self):
        from graphrag.validate import size_forms, validate, written_in

        self.assertTrue(any(written_in(f, '13 ⅜" Casing') for f in size_forms("13-3/8")))
        fact = {"chunk": "d#c1", "well": "TNT-GT-01", "property": "casing_depth", "qualifier": "actual",
                "context": {"casing_size_in": "13-3/8"}, "value": "1275", "unit": "m"}
        self.assertEqual(len(validate([fact], {"d#c1": 'Well TNT-GT-01: 13 ⅜" Casing at 1275'}, strict=True)[0]), 1)


class StrictFactTests(unittest.TestCase):
    def fact(self, size, value="978"):
        return {"chunk": "d#c1", "well": "68-32", "property": "casing_depth", "qualifier": "actual",
                "context": {"casing_size_in": size}, "value": value}

    def test_casing_sizes(self):
        from graphrag.validate import casing_size

        self.assertEqual(casing_size("5-1/2"), 5.5)
        self.assertEqual(casing_size('5-1/2"'), 5.5)
        self.assertEqual(casing_size("5.500"), 5.5)
        self.assertEqual(casing_size("13 3/8"), 13.375)
        for junk in ("10031", "8.33", "1-39", "2-99", "69", "2", "HRQ", "blank", '6-35"'):
            self.assertIsNone(casing_size(junk), junk)

    def test_strict_rejects_what_the_value_check_passes(self):
        from graphrag.validate import validate

        text = {"d#c1": "Well 68-32 with Rig #10031 ran 5-1/2 casing to 978 ft."}
        junk, rejected = validate([self.fact("10031")], text, strict=True)
        self.assertEqual((junk, rejected), ([], {"context is not a casing size": 1}))
        self.assertEqual(len(validate([self.fact("10031")], text)[0]), 1)
        self.assertEqual(len(validate([self.fact("5-1/2")], text, strict=True)[0]), 1)
        self.assertEqual(validate([self.fact("9-5/8")], text, strict=True)[1], {"context not in its chunk": 1})
        self.assertEqual(validate([self.fact("5-1/2", "5.5")], {"d#c1": text["d#c1"] + " 5.5"}, strict=True)[1],
                         {"value repeats its casing size": 1})


class RoutingTests(unittest.TestCase):
    def test_routing_and_plan_rules(self):
        from graphrag.baseline import asks_about_plan, names_several_wells

        self.assertTrue(names_several_wells("Which is deeper, AK-3 or 68-32?"))
        self.assertFalse(names_several_wells("How deep is AK-3?"))
        self.assertTrue(asks_about_plan("What was the planned depth?"))
        self.assertFalse(asks_about_plan("What was the depth?"))


class HeldOutSetTests(unittest.TestCase):
    def test_gold_values_are_written_in_their_chunks(self):
        from graphrag.data import load_chunks, load_questions
        from graphrag.validate import written_in

        text = {c.id: c.text for c in load_chunks()}
        questions, gold = load_questions("heldout")
        self.assertEqual({g for q in questions for g in q["gold"]}, set(gold))
        for fact in gold.values():
            self.assertTrue(all(c in text for c in fact["chunks"]), fact["id"])
            if not fact.get("derived"):
                forms = [fact["value"], *fact.get("alternatives", [])]
                self.assertTrue(any(written_in(v, text[c]) for v in forms for c in fact["chunks"]), fact["id"])


class DailySetTests(unittest.TestCase):
    def test_gold_pages_map_to_chunks_of_that_attachment_and_page(self):
        from graphrag.data import chunks_on_pages

        rows = [{"chunk_id": "a", "doc_id": "gdr882-ak3-appx-30-6-dailyreportsummaryrpt-1", "pages": [17]},
                {"chunk_id": "b", "doc_id": "gdr882-ak3-appx-28-6-dailyreportdetailrpt-1", "pages": [17]},
                {"chunk_id": "c", "doc_id": "gdr882-ak3-appx-28-6-dailyreportdetailrpt-1", "pages": [22, 23]}]
        self.assertEqual(chunks_on_pages([{"appx": "30", "page": 17}, {"appx": "28", "page": 23}], rows), ["a", "c"])

    def test_question_file_is_consistent(self):
        from graphrag.data import AK3_DAILY

        daily = json.loads(AK3_DAILY.read_text(encoding="utf-8"))
        self.assertIn("SIMULATED", daily["status"])
        self.assertEqual({g for q in daily["questions"] for g in q["gold"]}, {f["id"] for f in daily["facts"]})
        for fact in daily["facts"]:
            self.assertTrue(fact["sources"], fact["id"])


if __name__ == "__main__":
    unittest.main()
