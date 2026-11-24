"""Track B's lanes and coordinator (specification §8.1), with stand-in models: no server is needed."""
import dataclasses
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from graphrag import baseline, client, coordinator, events, factgraph, k4, lanes
from graphrag.data import Chunk
from graphrag.events import Event

GOLDEN = Path(__file__).parent / "fixtures/graphrag_answer_requests.json"
DEPTH_ANSWER = {"evidence": "The report states the depth.", "status": "answered",
                "answers": [{"value": "1,955", "unit": "ft", "chunk": "c0002", "quote": "1,955 feet"}]}
NOT_STATED = {"evidence": "", "status": "not_stated", "answers": []}


class RecordingClient:
    """Returns one fixed answer and keeps every request it was sent."""

    def __init__(self, answer=DEPTH_ANSWER):
        self.answer, self.calls = answer, []

    def chat(self, messages, schema=None, max_tokens=None):
        self.calls.append({"messages": messages, "schema": schema, "max_tokens": max_tokens})
        return SimpleNamespace(parsed=self.answer, content=json.dumps(self.answer), prompt_tokens=100,
                               completion_tokens=20, seconds=0.1, cached=False)


def recorded_requests() -> dict:
    """The requests two baseline runs send: the prototype questions, and the probe with multi-well routing."""
    chunks = baseline.pool("three")
    retriever = baseline.build("wells:bm25", chunks)
    retrieve = lambda q: ([c for c, _ in retriever.search(q, 5)], "")
    out = {}
    for name, kwargs in (("prototype", {"questions": "prototype"}),
                         ("probe_multi_well", {"questions": "probe", "multi_well_format": "evidence_first"})):
        recording = RecordingClient()
        baseline.answer_questions(retrieve, chunks, recording, **kwargs)
        # A hash of each whole request keeps the fixture small; any changed character changes it.
        out[name] = [hashlib.sha256(json.dumps([c["messages"], c["schema"], c["max_tokens"]], sort_keys=True)
                                    .encode("utf-8")).hexdigest() for c in recording.calls]
    return out


def plan(operation, **fields):
    """A complete query plan: every PLAN_SCHEMA field, empty unless given."""
    empty = {"well": "AK-3", "code": "", "non_productive": False, "npt_code": "", "date_from": "", "date_to": "",
             "group_by": "", "min_hours_per_day": 0, "depth_ft": 0}
    return {"operation": operation, **empty, **fields}


def sample_events():
    return [Event("2016-08-20", "0:00", "9:30", 9.5, 100, "DRIL", "drilling ahead", ["a"]),
            Event("2016-08-20", "9:30", "10:00", 0.5, 100, "SURV", "", ["b"]),
            Event("2016-08-20", "17:00", "18:00", 1.0, 176, "STUCK", "", ["c"], "KICK"),
            Event("2016-08-21", "0:00", "0:00", 24.0, 176, "KICK", "", ["d"], "KICK"),
            Event("2016-08-22", "0:00", "6:00", 6.0, 300, "DRIL", "", ["e", "a"])]


FACTS = [
    {"chunk": "gdr882_ak3_eowr#c0013", "well": "AK-3", "property": "casing_depth", "qualifier": "actual",
     "context": {"casing_size_in": "8-5/8"}, "value": "40", "source": "gdr882_ak3_eowr#t003"},
    {"chunk": "gdr882_ak3_eowr#c0012", "well": "AK-3", "property": "casing_depth", "qualifier": "planned",
     "context": {"casing_size_in": "8-5/8"}, "value": "40", "source": "gdr882_ak3_eowr#t002"},
    {"chunk": "gdr882_ak3_eowr#c0037", "well": "AK-3", "property": "non_productive_time", "qualifier": "actual",
     "context": None, "value": "115.0"},
]
FRAME_EOW = {"kind": "lookup", "report_type": "end_of_well", "plan": plan("not_answerable")}


def frame_with(query_plan):
    return {"kind": "over_time", "report_type": "daily", "plan": query_plan}


def sample_engine():
    """The three end-of-well reports of the bundle, five stand-in daily-report chunks (the sample events' sources)
    and three facts about AK-3."""
    daily = [Chunk(name, "ak3-dailyreport", page, "text", "Operations", f"Report For 2{page - 1}-Aug-16 AK-3 {name}")
             for name, page in (("a", 1), ("b", 1), ("c", 1), ("d", 2), ("e", 3))]
    return lanes.Engine(baseline.pool("three"), daily, sample_events(), FACTS, multi_well_retriever="perwell:bm25")


def flat(frame):
    """A frame as the model returns it: kind, report type and the plan's fields in one object."""
    return {"kind": frame["kind"], "report_type": frame["report_type"], **frame["plan"]}


def Q(text):  # noqa: N802 (reads as a constructor in the tests)
    return {"id": "live", "kind": "live", "question": text, "gold": []}


class ScriptedClient:
    """Returns `frame` to a framing call and `answer` to an answer call, and counts each."""

    def __init__(self, frame, answer):
        self.frame, self.answer, self.frame_calls, self.answer_calls = frame, answer, 0, 0

    def chat(self, messages, schema=None, max_tokens=None):
        framing = "kind" in (schema or {}).get("properties", {})
        self.frame_calls += framing
        self.answer_calls += not framing
        parsed = self.frame if framing else self.answer
        return SimpleNamespace(parsed=parsed, content=json.dumps(parsed), prompt_tokens=100, completion_tokens=20,
                               seconds=0.1, cached=False)


class RoleTests(unittest.TestCase):
    def test_roles_file_names_the_four_roles_on_known_endpoints(self):
        roles = client.load_roles()
        self.assertEqual(set(roles), {"frame", "answer", "extract", "embed"})
        self.assertEqual(roles["answer"], {"endpoint": "local-llama", "model": "qwen3-8b"})
        self.assertTrue(all(r["endpoint"] in client.load_endpoints() for r in roles.values()))

    def test_client_for_a_role_uses_its_endpoint_and_model(self):
        made = client.client_for("embed", cache_dir=None)
        self.assertEqual((made.endpoint.name, made.model), ("local-embed", "qwen3-embedding-0.6b"))

    def test_unknown_role_is_refused(self):
        with self.assertRaises(KeyError):
            client.client_for("summarize")


class PlanValueTests(unittest.TestCase):
    def setUp(self):
        self.events = sample_events()

    def test_total_hours_gives_one_number_in_hours(self):
        values, unit, text, rows = events.plan_value(plan("total_hours", code="DRIL"), self.events)
        self.assertEqual((values, unit), (["15.5"], "hours"))
        self.assertIn("= 15.5 (2 events on 2 dates)", text)
        self.assertEqual(len(rows), 2)

    def test_counts_dates_groups_and_depths(self):
        value = lambda *a, **k: events.plan_value(plan(*a, **k), self.events)[:2]
        self.assertEqual(value("count_events", non_productive=True), (["2"], ""))
        self.assertEqual(value("count_days", non_productive=True, min_hours_per_day=12), (["1"], ""))
        self.assertEqual(value("list_dates", non_productive=True), (["2016-08-20", "2016-08-21"], ""))
        self.assertEqual(value("first_date", code="DRIL"), (["2016-08-20"], ""))
        self.assertEqual(value("last_date", code="DRIL"), (["2016-08-22"], ""))
        self.assertEqual(value("top_group", group_by="code"), (["KICK"], ""))
        self.assertEqual(value("depth_on_date", date_from="2016-08-22"), (["300"], "ft"))
        self.assertEqual(value("depth_gain", date_from="2016-08-20", date_to="2016-08-22"), (["124"], "ft"))
        self.assertEqual(value("first_date_depth_at_least", depth_ft=150), (["2016-08-20"], ""))

    def test_no_match_gives_no_values_not_zero(self):
        self.assertEqual(events.plan_value(plan("total_hours", code="NOPE"), self.events), ([], "", "", []))
        self.assertEqual(events.plan_value(plan("not_answerable"), self.events), ([], "", "", []))
        self.assertEqual(events.plan_value(plan("total_hours", well="56-32"), self.events), ([], "", "", []))

    def test_run_plan_text_is_unchanged(self):
        for p in (plan("total_hours", code="DRIL"), plan("count_days", non_productive=True), plan("top_group")):
            self.assertEqual(events.run_plan(p, self.events), events.plan_value(p, self.events)[2:])


class AnswerOneTests(unittest.TestCase):
    def test_answer_questions_sends_the_same_requests_as_before(self):
        # The fixture was recorded from the code before answer_one was split out: the request cache and every
        # recorded run depend on these requests staying byte for byte the same.
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual((len(golden["prototype"]), len(golden["probe_multi_well"])), (31, 9))
        self.assertEqual(recorded_requests(), golden)

    def test_answer_one_scores_and_cites(self):
        by_id = {c.id: c for c in baseline.pool("three")}
        q = {"id": "live", "kind": "live", "question": "What total depth did well AK-3 reach?", "gold": []}
        recording = RecordingClient()
        row = baseline.answer_one(q, ["gdr882_ak3_eowr#c0002"], "", by_id, recording, {})
        self.assertEqual((row["status"], row["values"]), ("answered", ["1955"]))
        self.assertEqual(row["citations"][0]["chunk"], "gdr882_ak3_eowr#c0002")
        self.assertEqual((row["prompt_tokens"], len(recording.calls)), (100, 1))


class LaneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = sample_engine()

    def test_passages_for_one_well_come_from_its_report_only(self):
        ev = lanes.passages("What total depth did well AK-3 reach?", FRAME_EOW, self.engine)
        self.assertEqual((ev.lane, ev.exact, ev.answer_format, len(ev.passages)), ("passages", False, "status_first", 5))
        self.assertTrue(all(c.startswith("gdr882_ak3_eowr#") for c in ev.passages))

    def test_passages_with_no_well_and_no_date_still_answer(self):
        self.assertEqual(len(lanes.passages("What is the mud weight?", FRAME_EOW, self.engine).passages), 5)

    def test_several_wells_use_evidence_first_and_ten_passages(self):
        ev = lanes.passages("Which of AK-3 and 56-32 was drilled deeper?", FRAME_EOW, self.engine)
        self.assertEqual((ev.answer_format, len(ev.passages)), ("evidence_first", 10))
        self.assertEqual({c.split("#")[0] for c in ev.passages}, {"gdr882_ak3_eowr", "gdr1295_56-32_eowr"})

    def test_several_wells_without_a_multi_well_retriever_use_the_ordinary_one(self):
        engine = dataclasses.replace(self.engine, multi_well_retriever=None)
        ev = lanes.passages("Which of AK-3 and 56-32 was drilled deeper?", FRAME_EOW, engine)
        self.assertEqual((ev.answer_format, len(ev.passages)), ("status_first", 5))

    def test_daily_passages_keep_to_the_date_the_question_names(self):
        frame = {"kind": "lookup_by_date", "report_type": "daily", "plan": plan("not_answerable")}
        ev = lanes.passages("What happened on AK-3 on 21 August 2016?", frame, self.engine)
        self.assertEqual((ev.passages, ev.report_type), (["d"], "daily"))

    def test_daily_passages_without_a_daily_corpus_are_empty(self):
        engine = dataclasses.replace(self.engine, daily_chunks=[], events=[])
        frame = {"kind": "lookup_by_date", "report_type": "daily", "plan": plan("not_answerable")}
        self.assertTrue(lanes.passages("What happened on 21 August 2016?", frame, engine).empty)

    def test_well_facts_hide_planned_values_unless_asked(self):
        actual = lanes.well_facts("What casing depth did AK-3 reach?", FRAME_EOW, self.engine)
        self.assertTrue(actual.exact)
        self.assertEqual({f["qualifier"] for f in actual.facts}, {"actual"})
        self.assertEqual(set(actual.passages), {f["chunk"] for f in actual.facts})
        planned = lanes.well_facts("What was the planned casing depth of AK-3?", FRAME_EOW, self.engine)
        self.assertIn("planned", {f["qualifier"] for f in planned.facts})

    def test_well_facts_are_empty_for_an_unknown_well_or_no_well(self):
        self.assertTrue(lanes.well_facts("What depth did ZZ-9 reach?", FRAME_EOW, self.engine).empty)
        self.assertTrue(lanes.well_facts("What is the mud weight?", FRAME_EOW, self.engine).empty)

    def test_events_lane_reports_values_and_their_source_chunks(self):
        ev = lanes.events("How many hours of drilling?", frame_with(plan("total_hours", code="DRIL")), self.engine)
        self.assertEqual((ev.computed["values"], ev.computed["unit"]), (["15.5"], "hours"))
        self.assertEqual(ev.computed["source_chunks"], ["a", "e"])
        self.assertEqual((ev.passages, ev.exact, ev.report_type), (["a", "e"], True, "daily"))
        self.assertEqual(len(ev.computed["events"]), 2)

    def test_events_lane_is_empty_when_nothing_matches(self):
        self.assertTrue(lanes.events("x", frame_with(plan("total_hours", code="NOPE")), self.engine).empty)


class CoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = sample_engine()

    def test_schema_asks_kind_and_report_type_before_the_plan(self):
        names = list(coordinator.FRAME_SCHEMA["properties"])
        self.assertEqual(names[:2], ["kind", "report_type"])
        self.assertEqual(set(names[2:]), set(events.PLAN_SCHEMA["properties"]))
        self.assertEqual(coordinator.FRAME_SCHEMA["required"], names)
        self.assertEqual(coordinator.FRAME_SCHEMA["properties"]["kind"]["enum"],
                         ["lookup", "lookup_by_date", "across_wells", "over_time", "reasoning", "other"])

    def test_system_prompt_lists_the_wells_activity_codes(self):
        system = coordinator.frame_system(self.engine)
        self.assertIn("- DRIL:", system)
        self.assertIn("over_time", system)

    def test_routes(self):
        daily = {"kind": "lookup_by_date", "report_type": "daily", "plan": plan("not_answerable")}
        reasoning = {"kind": "reasoning", "report_type": "unknown", "plan": plan("not_answerable")}
        self.assertEqual(coordinator.route(frame_with(plan("total_hours"))), ["events"])
        self.assertEqual(coordinator.route(frame_with(plan("not_answerable"))), ["passages"])
        self.assertEqual(coordinator.route(daily), ["passages"])
        self.assertEqual(coordinator.route(FRAME_EOW), ["well_facts", "passages"])
        self.assertEqual(coordinator.route(FRAME_EOW, mode="exact"), ["well_facts"])
        self.assertEqual(coordinator.route(daily, mode="exact"), [])
        self.assertEqual(coordinator.route(reasoning), ["well_facts", "passages"])

    def test_computed_result_is_reported_by_code_with_one_call(self):
        scripted = ScriptedClient(flat(frame_with(plan("total_hours", code="DRIL"))), None)
        row = coordinator.answer(Q("How many hours of drilling on AK-3?"), self.engine, scripted, scripted)
        self.assertEqual((row["status"], row["lanes"], row["calls"]), ("answered", ["events"], 1))
        self.assertEqual((row["values"], row["units"]), (["15.5"], ["hours"]))
        self.assertEqual(row["values"], row["computed"]["values"])
        self.assertEqual(scripted.answer_calls, 0)
        self.assertEqual(row["citations"], [{"chunk": "a", "how": "event_graph"}, {"chunk": "e", "how": "event_graph"}])
        self.assertIn("= 15.5", row["answer_text"])

    def test_computed_result_is_scored_against_gold(self):
        gold = {"g1": {"id": "g1", "value": 15.5, "chunks": ["a"]}}
        q = dict(Q("How many hours of drilling on AK-3?"), gold=["g1"])
        scripted = ScriptedClient(flat(frame_with(plan("total_hours", code="DRIL"))), None)
        self.assertTrue(coordinator.answer(q, self.engine, scripted, scripted, gold)["correct"])

    def test_no_matching_events_falls_back_to_passages(self):
        scripted = ScriptedClient(flat(frame_with(plan("total_hours", code="NOPE"))), NOT_STATED)
        row = coordinator.answer(Q("How many hours of NOPE on AK-3?"), self.engine, scripted, scripted)
        self.assertTrue(row["fallback"])
        self.assertEqual((row["lanes"], row["calls"], row["values"], row["status"]), (["passages"], 2, [], "not_stated"))
        self.assertIsNone(row["computed"])

    def test_unparseable_frame_answers_from_end_of_well_passages(self):
        for broken in (None, DEPTH_ANSWER, {"kind": "poem", "report_type": "daily"}):
            scripted = ScriptedClient(broken, DEPTH_ANSWER)
            row = coordinator.answer(Q("What total depth did well AK-3 reach?"), self.engine, scripted, scripted)
            self.assertEqual((row["frame"]["kind"], row["frame"]["report_type"]), ("other", "unknown"))
            self.assertEqual((row["values"], row["calls"]), (["1955"], 2))
            self.assertIn("passages", row["lanes"])

    def test_end_of_well_answer_shows_the_wells_facts_before_the_passages(self):
        recording = RecordingClient()
        frames = ScriptedClient(flat(FRAME_EOW), None)
        row = coordinator.answer(Q("What casing depth did well AK-3 reach?"), self.engine, frames, recording)
        self.assertEqual(row["lanes"], ["well_facts", "passages"])
        prompt = recording.calls[0]["messages"][1]["content"]
        self.assertIn("AK-3 casing_depth at casing_size_in 8-5/8 = 40 [gdr882_ak3_eowr#c0013]", prompt)
        self.assertNotIn("(planned)", prompt)
        self.assertLess(prompt.index("casing_depth"), prompt.index("Passages:"))

    def test_exact_mode_with_nothing_in_the_graph_makes_no_answer_call(self):
        scripted = ScriptedClient(flat(FRAME_EOW), DEPTH_ANSWER)
        row = coordinator.answer(Q("What depth did ZZ-9 reach?"), self.engine, scripted, scripted, mode="exact")
        self.assertEqual((row["status"], row["values"], scripted.answer_calls), ("not_found_in_graph", [], 0))
        self.assertEqual((row["lanes"], row["calls"], row["mode"]), ([], 1, "exact"))
        self.assertIn("sources", row)

    def test_exact_mode_answers_from_facts_and_their_chunks_only(self):
        recording = RecordingClient()
        frames = ScriptedClient(flat(FRAME_EOW), None)
        row = coordinator.answer(Q("What casing depth did well AK-3 reach?"), self.engine, frames, recording, mode="exact")
        self.assertEqual(row["lanes"], ["well_facts"])
        self.assertEqual(row["passages"], 2)  # the chunks of the two facts that are not planned

    def test_code_reads_the_well_and_several_wells_mean_across_wells(self):
        wrong = flat({"kind": "lookup", "report_type": "end_of_well", "plan": plan("not_answerable", well="AK-9")})
        frame, _ = coordinator.frame_question("Which of AK-3 and 56-32 is deeper?", self.engine, ScriptedClient(wrong, None))
        self.assertEqual(frame["kind"], "across_wells")
        frame, _ = coordinator.frame_question("What depth did AK-3 reach?", self.engine, ScriptedClient(wrong, None))
        self.assertEqual((frame["kind"], frame["plan"]["well"]), ("lookup", "AK-3"))

    def test_a_forced_lane_replaces_the_route(self):
        scripted = ScriptedClient(flat(frame_with(plan("total_hours", code="DRIL"))), DEPTH_ANSWER)
        row = coordinator.answer(Q("What total depth did well AK-3 reach?"), self.engine, scripted, scripted, lane="passages")
        self.assertEqual(row["lanes"], ["passages"])
        with self.assertRaises(KeyError):
            coordinator.answer(Q("x"), self.engine, scripted, scripted, lane="poetry")

    def test_several_forced_lanes_run_in_the_order_given(self):
        scripted = ScriptedClient(None, DEPTH_ANSWER)
        row = coordinator.answer(Q("What casing depth did well AK-3 reach?"), self.engine, scripted, scripted,
                                 lane=["well_facts", "passages"])
        self.assertEqual(row["lanes"], ["well_facts", "passages"])


class PooledRunTests(unittest.TestCase):
    def test_pool_prefixes_ids_and_names_the_expected_lane(self):
        questions, gold = coordinator.pooled(["prototype", "probe"])
        self.assertEqual(len(questions), 31 + 9)
        self.assertEqual(len({q["id"] for q in questions}), 40)
        self.assertTrue(all(q["id"].startswith(f"{q['set']}:") and q["expected"] == "end_of_well" for q in questions))
        self.assertTrue(all(g in gold for q in questions for g in q["gold"]))

    def test_every_question_set_has_an_expected_lane(self):
        self.assertEqual(set(coordinator.EXPECTED), set(baseline.QUESTION_SETS))
        self.assertEqual(coordinator.EXPECTED["ak3_events_heldout"], "events")
        self.assertEqual(coordinator.EXPECTED["ak3_daily"], "daily")

    def test_routing_is_judged_against_the_source_set(self):
        rows = [{"expected": "events", "lanes": ["events"], "frame": {"report_type": "daily"}},
                {"expected": "events", "lanes": ["passages"], "frame": {"report_type": "daily"}},
                {"expected": "daily", "lanes": ["passages"], "frame": {"report_type": "daily"}},
                {"expected": "daily", "lanes": ["well_facts", "passages"], "frame": {"report_type": "end_of_well"}},
                {"expected": "end_of_well", "lanes": ["well_facts", "passages"], "frame": {"report_type": "unknown"}},
                {"expected": "end_of_well", "lanes": ["events"], "frame": {"report_type": "daily"}}]
        self.assertEqual([coordinator.rightly_routed(r) for r in rows], [True, False, True, False, True, False])

    def test_summary_counts_per_set_and_adds_frame_and_answer_cost(self):
        row = lambda name, correct, routed, calls: {
            "set": name, "correct": correct, "rightly_routed": routed, "fallback": False, "calls": calls,
            "prompt_tokens": 1000 * (calls - 1), "completion_tokens": 50 * (calls - 1), "seconds": 1.0 * (calls - 1),
            "frame_prompt_tokens": 600, "frame_completion_tokens": 40, "frame_seconds": 0.5}
        summary = coordinator.summarize_pool([row("a", True, True, 2), row("a", False, True, 2), row("b", True, False, 1)])
        self.assertEqual((summary["correct_total"], summary["rightly_routed"]), ("2/3", "2/3"))
        self.assertEqual(summary["by_set"]["a"]["correct"], "1/2")
        self.assertEqual(summary["by_set"]["b"]["calls_per_question"], 1.0)
        self.assertEqual(summary["per_question"]["prompt_tokens"], round((1600 + 1600 + 600) / 3, 1))

    def test_a_pooled_run_answers_through_the_coordinator_and_records_its_cost(self):
        scripted = ScriptedClient(flat(FRAME_EOW), DEPTH_ANSWER)
        questions, gold = coordinator.pooled(["prototype"])
        out = coordinator.run_pool(questions[:3], gold, sample_engine(), scripted, scripted, quiet=True)
        self.assertEqual((out["questions"], len(out["rows"]), scripted.frame_calls), (3, 3, 3))
        self.assertTrue(all(r["set"] == "prototype" and "rightly_routed" in r for r in out["rows"]))


class K4VersionTests(unittest.TestCase):
    RUN = {"question_set": ["prototype"], "mode": "allow_fallback",
           "roles": {"frame": {"endpoint": "local-llama", "model": "qwen3-8b"},
                     "answer": {"endpoint": "local-llama", "model": "qwen3-8b"}},
           "rows": [
               {"id": "prototype:q01", "set": "prototype", "status": "answered", "values": ["15.5"], "units": ["hours"],
                "correct": True, "citations": [{"chunk": "a", "how": "event_graph"}], "lanes": ["events"],
                "frame": {"kind": "over_time"}, "mode": "allow_fallback", "calls": 1, "prompt_tokens": 0,
                "completion_tokens": 0, "seconds": 0.0, "frame_prompt_tokens": 600, "frame_completion_tokens": 40,
                "frame_seconds": 0.5},
               {"id": "prototype:q02", "set": "prototype", "status": "not_found_in_graph", "values": [], "units": [],
                "correct": False, "citations": [], "lanes": [], "frame": {"kind": "lookup"}, "mode": "exact", "calls": 1,
                "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0, "frame_prompt_tokens": 600,
                "frame_completion_tokens": 40, "frame_seconds": 0.5}]}

    def records(self, run):
        with tempfile.TemporaryDirectory() as temporary:
            Path(temporary, "r.json").write_text(json.dumps(run), encoding="utf-8")
            with patch("graphrag.k4.RESULTS", Path(temporary)):
                return k4.records("r")

    def test_coordinator_rows_become_version_0_2_records(self):
        import jsonschema
        schema = json.loads(k4.SCHEMA.read_text(encoding="utf-8"))
        records = self.records(self.RUN)
        self.assertEqual({r["k4_version"] for r in records}, {"0.2"})
        self.assertEqual(records[0]["pipeline"], {"base": "coordinator", "lanes": ["events"], "mode": "allow_fallback",
                                                  "frame_kind": "over_time"})
        self.assertEqual(records[0]["cost"], {"calls": 1, "prompt_tokens": 600, "completion_tokens": 40, "seconds": 0.5,
                                              "cost_usd": 0.0})
        self.assertEqual(records[0]["models"], {"frame": "local-llama:qwen3-8b", "answer": "local-llama:qwen3-8b"})
        self.assertEqual((records[0]["question_set"], records[0]["question_id"]), ("prototype", "prototype:q01"))
        self.assertEqual(records[0]["question"], "What total depth did well AK-3 reach?")
        self.assertEqual(records[1]["status"], "not_found_in_graph")
        for record in records:
            jsonschema.validate(record, schema)

    def test_earlier_runs_still_write_version_0_1(self):
        self.assertEqual({r["k4_version"] for r in k4.records("E26_plain_routed")}, {"0.1"})


class FactGraphTests(unittest.TestCase):
    def setUp(self):
        self.graph = factgraph.to_graph(FACTS)

    def nodes(self, label):
        return [n for n in self.graph["nodes"] if n["label"] == label]

    def relationships(self, kind):
        return [r for r in self.graph["relationships"] if r["type"] == kind]

    def test_every_fact_is_a_node_under_its_well_with_its_chunk(self):
        self.assertEqual([len(self.nodes(label)) for label in ("Well", "Fact", "Chunk", "Document")], [1, 3, 3, 1])
        self.assertEqual([len(self.relationships(kind)) for kind in ("HAS_FACT", "FROM", "HAS_CHUNK", "DESCRIBED_BY")],
                         [3, 3, 3, 1])
        self.assertEqual(self.nodes("Well")[0], {"label": "Well", "key": "AK-3", "properties": {"name": "AK-3"}})
        self.assertEqual(self.nodes("Document")[0]["key"], "gdr882_ak3_eowr")
        self.assertEqual(self.nodes("Chunk")[0], {"label": "Chunk", "key": "gdr882_ak3_eowr#c0012", "properties": {}})

    def test_planned_and_actual_values_stay_separate_and_name_their_source(self):
        facts = self.nodes("Fact")
        self.assertEqual(sorted(n["properties"]["qualifier"] for n in facts), ["actual", "actual", "planned"])
        self.assertEqual({n["properties"]["source"] for n in facts}, {"table_mapping", "llm"})
        casing = next(n for n in facts if n["properties"]["qualifier"] == "planned")
        self.assertEqual(casing["properties"]["context"], '{"casing_size_in": "8-5/8"}')
        self.assertEqual(casing["properties"]["value"], "40")

    def test_casing_string_takes_actual_values_only(self):
        casing = self.nodes("CasingString")
        self.assertEqual(len(casing), 1)
        self.assertEqual((casing[0]["key"], casing[0]["properties"]), ("AK-3|8-5/8", {"casing_size_in": "8-5/8", "depth": "40"}))
        self.assertEqual(self.relationships("HAS_CASING")[0]["from"], ["Well", "AK-3"])

    def test_hole_sections_come_from_hole_size_facts(self):
        hole = {"chunk": "gdr882_ak3_eowr#c0013", "well": "AK-3", "property": "hole_size", "qualifier": "actual",
                "context": None, "value": "12-1/4"}
        graph = factgraph.to_graph(FACTS + [hole])
        sections = [n for n in graph["nodes"] if n["label"] == "HoleSection"]
        self.assertEqual([(n["key"], n["properties"]) for n in sections], [("AK-3|12-1/4", {"hole_size_in": "12-1/4"})])
        self.assertEqual(sum(r["type"] == "HAS_SECTION" for r in graph["relationships"]), 1)

    def test_no_dangling_relationships_and_stable_output(self):
        keys = {(n["label"], n["key"]) for n in self.graph["nodes"]}
        self.assertEqual(len(keys), len(self.graph["nodes"]))
        self.assertTrue(all(tuple(r["from"]) in keys and tuple(r["to"]) in keys for r in self.graph["relationships"]))
        self.assertEqual(self.graph, factgraph.to_graph(list(reversed(FACTS))))

    def test_a_fact_without_one_well_name_is_left_out(self):
        nameless = dict(FACTS[2], well="")
        self.assertEqual(len([n for n in factgraph.to_graph([nameless])["nodes"] if n["label"] == "Fact"]), 0)

    def test_k1_version_1_chunk_ids_give_the_file_as_the_document(self):
        fact = dict(FACTS[2], chunk="f62efbee00767a3e7:s6:c0")
        documents = [n["key"] for n in factgraph.to_graph([fact])["nodes"] if n["label"] == "Document"]
        self.assertEqual(documents, ["f62efbee00767a3e7"])


if __name__ == "__main__":
    unittest.main()
