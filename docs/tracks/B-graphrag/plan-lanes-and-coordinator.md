# Lanes and coordinator: implementation plan

**Status: carried out on 24 November 2026.** What was built, and where it differs from this plan, is in the [log](log.md), entries B-C37 to B-C42. Differences: activity code `DRIL` in the tests; request hashes instead of request text in the fixture; the answer prompt keeps the measured design (fact sheet before the passages lane's hits) instead of merging passages; `to_graph(facts)` takes no chunks; the real export is `E27_fact_graph`. The measurement (E33) is still to run.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put Track B's three answer paths behind one lane interface, add the coordinator that picks a lane per question, and export the fact graph as nodes and relationships, all testable without a model server.

**Architecture:** A lane is a function `(question, frame, engine) -> Evidence`. The coordinator makes one framing call, picks lanes in code, and either reports a computed result in code or makes one answer call. Existing commands (`graphrag.baseline`, `graphrag.events`) keep their behaviour and their exact prompts, because recorded runs and the request cache depend on them.

**Tech stack:** Python 3.12, standard library, `httpx`, `numpy`; `unittest` with stand-in clients. No new dependency.

**Spec:** [docs/PROJECT_DESIGN.md](../../PROJECT_DESIGN.md) §4.1 (model roles), §8.1 (coordinator and lanes), §8.3 (answer rules), §8.5 (graph model). Tasks E3 to E6 of [plan §7](../../DEVELOPMENT_PLAN.md#7-what-to-do-now). Decisions: Track B log B-D36, B-C35.

**Not in this plan:** the reasoning lane (E7), reading from PostgreSQL and Neo4j (E2, needs Hung's shared stores), the FastAPI service, the React frontend, and the measurement runs E32 and E33 (they need the desktop GPU; Task 6 gives the command).

## Global constraints

- Open-weight models only, through `graphrag/client.py`. No commercial API, no new package.
- The model never chooses a lane freely and never writes a query that runs. A plan is JSON checked against a schema; code runs it (spec §8.1, §10.2).
- `python -m graphrag.baseline answer` and `python -m graphrag.events answer` must send byte-identical requests after this change. The request cache is keyed by the whole request, and E14 to E31 are reproduced from it.
- `graphrag.events.run_plan(plan, events, well)` keeps its signature and its result text. Track C's `platform/load_events_neo4j.py` replays 58 recorded plans against that text.
- Question sets in `graphrag/gold/` are frozen. No file there changes.
- Files are LF. Tests: `python -m unittest discover -s tests -p "test_graphrag*.py"`.
- Commits are authored as the user with no AI attribution. `git pull --rebase` before pushing.
- Every design choice goes into [log.md](log.md) the same day (Task 8).

## Review focus

Inputs the spec implies and that are most likely to bite a user of the application. Each has a test in the task named.

1. A question that names no well and no date ("What is the mud weight?"): the passages lane must still return passages, not crash on an empty well set. Task 4.
2. The framing call returns invalid JSON or nothing: the coordinator must fall back to passages for an end-of-well report, not raise. Task 5.
3. A plan for a well, code or period with no events: the answer is "not stated", never zero, and in `allow_fallback` mode passages run instead. Task 5.
4. `mode="exact"` with nothing in the graphs: status `not_found_in_graph`, no model answer call, closest passages returned as sources. Task 5.
5. A question naming a well the fact graph does not hold: the well-facts lane returns empty evidence and the route falls back to passages. Task 4 and Task 5.

## File structure

| File | Responsibility |
|---|---|
| `configs/graphrag/roles.json` (create) | Which endpoint and model serve each role |
| `graphrag/client.py` (modify) | `load_roles`, `client_for` |
| `graphrag/events.py` (modify) | `plan_value`: a plan's result as values, unit, text and events; `run_plan` wraps it |
| `graphrag/baseline.py` (modify) | `answer_one`: one question from hits and graph text to a scored row; `answer_questions` loops over it |
| `graphrag/lanes.py` (create) | `Evidence`, `Engine`, and the lanes `passages`, `well_facts`, `events` |
| `graphrag/coordinator.py` (create) | `FRAME_SCHEMA`, `frame_question`, `route`, `answer`, and the command line for pooled runs |
| `graphrag/factgraph.py` (create) | Validated facts to nodes and relationships (spec §8.5) |
| `graphrag/k4.py`, `schemas/k4_answer_record.schema.json` (modify) | K4 version 0.2: `lanes`, `frame`, `mode` |
| `graphrag/ui.py` (modify) | `ask` goes through the coordinator |
| `tests/test_graphrag_lanes.py` (create) | Tests for Tasks 1 to 7 |

---

### Task 1: Model roles

**Files:**
- Create: `configs/graphrag/roles.json`
- Modify: `graphrag/client.py`
- Test: `tests/test_graphrag_lanes.py`

**Interfaces:**
- Produces: `load_roles(path: Path = ROLES) -> dict[str, dict]` returning `{role: {"endpoint": str, "model": str}}`; `client_for(role: str, roles: dict | None = None, **kwargs) -> ModelClient`. Roles are exactly `frame`, `answer`, `extract`, `embed`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run** `python -m unittest tests.test_graphrag_lanes.RoleTests` — expect `AttributeError: load_roles`.

- [ ] **Step 3: Create `configs/graphrag/roles.json`** with these values: `frame` and `answer` on `local-llama` / `qwen3-8b`; `extract` on `local-llama-2` / `qwen3-4b`; `embed` on `local-embed` / `qwen3-embedding-0.6b`.

- [ ] **Step 4: Implement `load_roles` and `client_for` in `graphrag/client.py`**, next to `load_endpoints`. `ROLES = ENDPOINTS.with_name("roles.json")`.

- [ ] **Step 5: Run the tests** — expect 3 passing.

- [ ] **Step 6: Commit** `Track B: model roles in configuration (D-62)`.

---

### Task 2: A plan's result as values

**Files:**
- Modify: `graphrag/events.py` (`run_plan`, lines 156-224)
- Test: `tests/test_graphrag_lanes.py`

**Interfaces:**
- Produces: `plan_value(plan: dict, events: list[Event], well: str = WELL) -> tuple[list[str], str, str, list[Event]]` returning `(values, unit, text, rows)`. `run_plan` becomes `values, unit, text, rows = plan_value(...); return text, rows`.

Values and units per operation:

| Operation | `values` | `unit` |
|---|---|---|
| `total_hours` | `[f"{hours:g}"]` | `"hours"` |
| `count_events`, `count_days` | `[str(n)]` | `""` |
| `list_dates` | the sorted dates | `""` |
| `first_date`, `last_date`, `first_date_depth_at_least` | `[date]` | `""` |
| `top_group` | `[best]` (the code or the date) | `""` |
| `depth_on_date` | `[str(depth)]` | `"ft"` |
| `depth_gain` | `[str(second - first)]` | `"ft"` |
| no match, or `not_answerable` | `[]` | `""` |

- [ ] **Step 1: Write the failing tests.** Reuse the events fixture of `EventGraphTests` in `tests/test_graphrag.py` (copy its `setUp` events).

```python
class PlanValueTests(unittest.TestCase):
    def test_total_hours_gives_one_number_in_hours(self):
        values, unit, text, rows = events.plan_value(plan("total_hours", code="DRL"), self.events)
        self.assertEqual((values, unit), ([f"{sum(e.hours for e in rows):g}"], "hours"))
        self.assertIn(f"= {values[0]}", text)

    def test_dates_and_depths(self):
        self.assertEqual(events.plan_value(plan("list_dates", non_productive=True), self.events)[0],
                         sorted({e.date for e in self.events if e.npt_code}))
        values, unit, _, _ = events.plan_value(plan("depth_on_date", date_from=self.events[0].date), self.events)
        self.assertEqual(unit, "ft")
        self.assertTrue(values[0].isdigit())

    def test_no_match_gives_no_values_not_zero(self):
        self.assertEqual(events.plan_value(plan("total_hours", code="NOPE"), self.events), ([], "", "", []))

    def test_run_plan_text_is_unchanged(self):
        for p in (plan("total_hours", code="DRL"), plan("count_days", non_productive=True), plan("top_group")):
            self.assertEqual(events.run_plan(p, self.events), events.plan_value(p, self.events)[2:])
```

`plan(operation, **fields)` is a test helper that fills every `PLAN_SCHEMA` field with its empty value (`""`, `False`, `0`) and `well="AK-3"`.

- [ ] **Step 2: Run** — expect `AttributeError: plan_value`.

- [ ] **Step 3: Rename the body of `run_plan` to `plan_value`** and make each `return` give `(values, unit, text, rows)`; add `run_plan` as the two-line wrapper. Change no result text.

- [ ] **Step 4: Run** `python -m unittest tests.test_graphrag_lanes.PlanValueTests tests.test_graphrag.EventGraphTests` — all pass.

- [ ] **Step 5: Check the recorded plans still replay.** Run `python -m unittest tests.test_graphrag_ui` — passes (it reruns recorded plans on `E28_events.json`).

- [ ] **Step 6: Commit** `Track B: a plan's result as values, for answers reported by code`.

---

### Task 3: `answer_one`

**Files:**
- Modify: `graphrag/baseline.py` (`answer_questions`, lines 243-310)
- Test: `tests/test_graphrag_lanes.py`

**Interfaces:**
- Produces: `answer_one(q: dict, hits: list[str], graph: str, by_id: dict[str, Chunk], client: ModelClient, gold: dict, *, facts: dict[str, list[str]] | None = None, withhold_unsupported: bool = False, max_tokens: int = 400, answer_format: str = "status_first", system_note: str = "") -> dict`. It returns the row `answer_questions` builds today, with the same keys. `answer_questions` keeps its signature, picks the format and token limit for multi-well questions itself, calls `answer_one`, and prints the same progress line.

- [ ] **Step 1: Write the failing tests.** `RecordingClient` stores every `messages`, `schema` and `max_tokens` it is given and returns a fixed `status: answered` answer citing `c0002`.

```python
class AnswerOneTests(unittest.TestCase):
    def test_answer_questions_sends_the_same_requests_as_before(self):
        # Golden requests recorded from the code before the refactor (Step 2).
        chunks = baseline.pool("three")
        recording = RecordingClient()
        baseline.answer_questions(lambda q: ([c for c, _ in baseline.build("wells:bm25", chunks).search(q, 5)], ""),
                                  chunks, recording, questions="prototype")
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual([[m["content"] for m in call["messages"]] for call in recording.calls], golden)

    def test_answer_one_scores_and_cites(self):
        chunks = baseline.pool("three")
        by_id = {c.id: c for c in chunks}
        q = {"id": "live", "kind": "live", "question": "What total depth did well AK-3 reach?", "gold": []}
        row = baseline.answer_one(q, ["gdr882_ak3_eowr#c0002"], "", by_id, RecordingClient(), {})
        self.assertEqual(row["status"], "answered")
        self.assertEqual(row["citations"][0]["chunk"], "gdr882_ak3_eowr#c0002")
        self.assertIn("prompt_tokens", row)
```

- [ ] **Step 2: Record the golden requests before touching `baseline.py`.** Run the first test's body once with the current code and write the list of message contents to `tests/fixtures/graphrag_prototype_requests.json` (`GOLDEN`). 31 entries.

- [ ] **Step 3: Run** — the first test passes (nothing changed yet), the second fails with `AttributeError: answer_one`.

- [ ] **Step 4: Move the loop body of `answer_questions` into `answer_one`.** `answer_questions` builds `by_id`, loads questions and gold, and for each question decides `routed`, `chosen` and the token limit as today, then calls `answer_one`.

- [ ] **Step 5: Run** `python -m unittest tests.test_graphrag_lanes.AnswerOneTests tests.test_graphrag tests.test_graphrag_ui` — all pass.

- [ ] **Step 6: Commit** `Track B: answer_one, one question from evidence to a scored row`.

---

### Task 4: Evidence, Engine and the three lanes

**Files:**
- Create: `graphrag/lanes.py`
- Test: `tests/test_graphrag_lanes.py`

**Interfaces:**
- Consumes: `baseline.build`, `baseline.pool`, `baseline.fact_sheet`, `baseline.asks_about_plan`, `baseline.names_several_wells`, `retrieval.well_names`, `retrieval.question_dates`, `validate.validate`, `events.plan_value`, `events.build_events`.
- Produces:

```python
@dataclass
class Evidence:
    lane: str                      # "passages", "well_facts" or "events"
    exact: bool                    # True for facts and computed results, False for passages
    passages: list[str] = field(default_factory=list)   # chunk IDs, best first
    facts: list[dict] = field(default_factory=list)      # validated fact records (tables.py's fields)
    computed: dict | None = None   # {"plan", "text", "values", "unit", "events": [dict], "source_chunks": [str]}
    answer_format: str = "status_first"
    report_type: str = "end_of_well"

    @property
    def empty(self) -> bool: ...   # no passages, no facts and no computed values

@dataclass
class Engine:
    eow_chunks: list[Chunk]
    daily_chunks: list[Chunk]
    events: list[Event]
    facts: list[dict]              # already validated
    multi_well_retriever: str | None = "perwell:fusion:bm25+dense:qwen3-embedding-0.6b"

    @classmethod
    def load(cls, fact_runs: list[str] | None = None, k1: bool = False) -> "Engine": ...
    def chunks(self, report_type: str) -> list[Chunk]: ...
    def by_id(self) -> dict[str, Chunk]: ...          # both pools

def passages(question: str, frame: dict, engine: Engine) -> Evidence
def well_facts(question: str, frame: dict, engine: Engine) -> Evidence
def events(question: str, frame: dict, engine: Engine) -> Evidence
LANES = {"passages": passages, "well_facts": well_facts, "events": events}
```

The settings each lane uses are today's baseline (B-D23, B-D26), not new choices:

| Case | Retriever | k | Answer format |
|---|---|---|---|
| End-of-well, one well or none | `wells:bm25` over `eow_chunks` | 5 | `status_first` |
| End-of-well, several wells, and `multi_well_retriever` set | that retriever | 10 | `evidence_first` |
| Daily (`frame["report_type"] == "daily"`) | `dates:wells:bm25` over `daily_chunks` | 5 | `status_first` |

- `well_facts` returns the facts whose well is one of `well_names(question)`, without `planned` facts unless `asks_about_plan(question)`; its `passages` are those facts' chunk IDs, without duplicates. Empty when no well is named or no fact matches.
- `events` runs `plan_value(frame["plan"], engine.events)`. `computed["source_chunks"]` is the events' chunks in order without duplicates; `passages` is the first 5 of them. Empty when the plan gives no values.
- `Engine.load` reads `baseline.pool("three")`; the daily chunks and events through `events.inputs(k1)` and `build_events`; and the facts of `fact_runs` validated with `strict=True`. With `fact_runs=None` it uses the run names in `graphrag/results/E27_design_prototype.json` (`fact_sheet` key), as `ui.sheet_facts` does today. A missing daily corpus leaves `daily_chunks` and `events` empty instead of raising.
- Retrievers are built once per engine and report type (cache them on the engine).

- [ ] **Step 1: Write the failing tests.** Build a small engine by hand: `eow_chunks = baseline.pool("three")`, two daily chunks and four events from the `EventGraphTests` fixture, and three facts for AK-3 (one `planned`).

```python
class LaneTests(unittest.TestCase):
    def test_passages_for_one_well_come_from_its_report_only(self):
        ev = lanes.passages("What total depth did well AK-3 reach?", FRAME_EOW, self.engine)
        self.assertEqual((ev.lane, ev.exact, ev.answer_format, len(ev.passages)), ("passages", False, "status_first", 5))
        self.assertTrue(all(c.startswith("gdr882_ak3_eowr#") for c in ev.passages))

    def test_passages_with_no_well_and_no_date_still_answer(self):
        self.assertEqual(len(lanes.passages("What is the mud weight?", FRAME_EOW, self.engine).passages), 5)

    def test_several_wells_use_evidence_first_and_ten_passages(self):
        engine = dataclasses.replace(self.engine, multi_well_retriever="perwell:bm25")
        ev = lanes.passages("Which of AK-3 and 56-32 was drilled deeper?", FRAME_EOW, engine)
        self.assertEqual((ev.answer_format, len(ev.passages)), ("evidence_first", 10))

    def test_well_facts_hide_planned_values_unless_asked(self):
        actual = lanes.well_facts("What casing depth did AK-3 reach?", FRAME_EOW, self.engine)
        self.assertTrue(actual.exact)
        self.assertTrue(all(f["qualifier"] != "planned" for f in actual.facts))
        planned = lanes.well_facts("What was the planned casing depth of AK-3?", FRAME_EOW, self.engine)
        self.assertTrue(any(f["qualifier"] == "planned" for f in planned.facts))
        self.assertEqual(set(actual.passages), {f["chunk"] for f in actual.facts})

    def test_well_facts_are_empty_for_an_unknown_well(self):
        self.assertTrue(lanes.well_facts("What depth did ZZ-9 reach?", FRAME_EOW, self.engine).empty)

    def test_events_lane_reports_values_and_their_source_chunks(self):
        ev = lanes.events("How many hours of drilling?", frame_with(plan("total_hours", code="DRL")), self.engine)
        self.assertEqual(ev.computed["unit"], "hours")
        self.assertEqual(ev.passages, ev.computed["source_chunks"][:5])
        self.assertTrue(ev.exact)

    def test_events_lane_is_empty_when_nothing_matches(self):
        self.assertTrue(lanes.events("x", frame_with(plan("total_hours", code="NOPE")), self.engine).empty)
```

`FRAME_EOW = {"kind": "lookup", "report_type": "end_of_well", "plan": plan("not_answerable")}`; `frame_with(p)` gives `{"kind": "over_time", "report_type": "daily", "plan": p}`.

- [ ] **Step 2: Run** — expect `ModuleNotFoundError: graphrag.lanes`.
- [ ] **Step 3: Implement `graphrag/lanes.py`** to the interface above.
- [ ] **Step 4: Run** `python -m unittest tests.test_graphrag_lanes.LaneTests` — 7 pass.
- [ ] **Step 5: Commit** `Track B: three lanes behind one interface (B-D36)`.

---

### Task 5: The coordinator

**Files:**
- Create: `graphrag/coordinator.py`
- Test: `tests/test_graphrag_lanes.py`

**Interfaces:**
- Consumes: Task 3's `answer_one`, Task 4's `Engine`, `Evidence`, `LANES`, `events.PLAN_SCHEMA`, `events.PLAN_SYSTEM`, `events.code_list`, `events.RESULT_NOTE`.
- Produces:

```python
KINDS = ("lookup", "lookup_by_date", "across_wells", "over_time", "reasoning", "other")
REPORT_TYPES = ("end_of_well", "daily", "both", "unknown")
FRAME_SCHEMA: dict   # object: "kind", "report_type", then every PLAN_SCHEMA property; all required
def frame_system(engine: Engine) -> str
def frame_question(question: str, engine: Engine, client) -> tuple[dict, Call | None]
def route(frame: dict, mode: str = "allow_fallback") -> list[str]
def answer(q: dict, engine: Engine, frame_client, answer_client, gold: dict | None = None,
           mode: str = "allow_fallback", lane: str | None = None) -> dict
```

Rules, all in code:

- **Frame.** One call with `FRAME_SCHEMA`, `max_tokens=260`. The frame is `{"kind", "report_type", "plan": {the PLAN_SCHEMA fields}}`. If the call returns nothing parseable, the frame is `{"kind": "other", "report_type": "unknown", "plan": {"operation": "not_answerable", ...}}`. When `well_names(question)` finds exactly one well, it replaces `plan["well"]`. When the question names two or more wells, `kind` becomes `across_wells`.
- **System prompt.** `frame_system` is `PLAN_SYSTEM + code_list(engine.events)` followed by one paragraph that defines the two new fields: the six kinds with one example each from spec §8.1's table, and the four report types. It says to use operation `not_answerable` unless `kind` is `over_time`.
- **Route.**

| Frame | Lanes, in order |
|---|---|
| `kind == "over_time"` and `plan["operation"] != "not_answerable"` | `["events"]` |
| `report_type == "daily"` | `["passages"]` |
| anything else (`end_of_well`, `both`, `unknown`; `reasoning` until its lane exists) | `["well_facts", "passages"]` |

  In `mode="exact"` the `passages` lane is removed from the route. A `lane` argument, when given, replaces the route with that one lane.
- **Run and fall back.** Run the routed lanes. In `allow_fallback` mode, if every lane's evidence is empty, run `passages` for the frame's report type (end-of-well when `unknown`) and set `fallback: True`.
- **Report or answer.**
  - Computed values present: no answer call. The row has `status: "answered"`, `values` normalized with `scoring.normalize`, `units`, `answer_text` equal to the computed text, and `citations` of `{"chunk": c, "how": "event_graph"}` for the source chunks. It is scored with `scoring.score_answer`.
  - `mode="exact"` and no exact evidence: no answer call. `status: "not_found_in_graph"`, no values, and `sources` holding the passages the passages lane would give (up to 5; none if no report names the well).
  - Otherwise one `answer_one` call. Passages are the lanes' passages merged in route order without duplicates. The graph text is the well-facts sheet (`baseline.fact_sheet(facts, limit=12)`, for the wells named, as `ui.fact_sheet_for` builds it). The answer format is the passages lane's, or `evidence_first` when only facts were used. `system_note` is empty.
- **Row.** Every row carries, on top of `answer_one`'s keys: `frame`, `lanes` (the lanes that gave evidence), `mode`, `fallback`, `computed` (or `None`), `calls` (1 or 2), and `frame_prompt_tokens`, `frame_completion_tokens`, `frame_seconds`. `answer_one`'s `prompt_tokens`, `completion_tokens` and `seconds` are 0 when no answer call was made.

- [ ] **Step 1: Write the failing tests.** `ScriptedClient(frame, answer)` returns `frame` when the schema has a `kind` property and `answer` otherwise, and counts calls of each kind.

```python
class CoordinatorTests(unittest.TestCase):
    def test_schema_asks_kind_and_report_type_before_the_plan(self):
        names = list(coordinator.FRAME_SCHEMA["properties"])
        self.assertEqual(names[:2], ["kind", "report_type"])
        self.assertEqual(set(names[2:]), set(events.PLAN_SCHEMA["properties"]))
        self.assertEqual(coordinator.FRAME_SCHEMA["required"], names)

    def test_routes(self):
        self.assertEqual(coordinator.route(frame_with(plan("total_hours"))), ["events"])
        self.assertEqual(coordinator.route({"kind": "lookup_by_date", "report_type": "daily", "plan": plan("not_answerable")}), ["passages"])
        self.assertEqual(coordinator.route(FRAME_EOW), ["well_facts", "passages"])
        self.assertEqual(coordinator.route(FRAME_EOW, mode="exact"), ["well_facts"])
        self.assertEqual(coordinator.route({"kind": "reasoning", "report_type": "unknown", "plan": plan("not_answerable")}),
                         ["well_facts", "passages"])

    def test_computed_result_is_reported_by_code_with_one_call(self):
        scripted = ScriptedClient(frame=flat(frame_with(plan("total_hours", code="DRL"))), answer=None)
        row = coordinator.answer(Q("How many hours of drilling on AK-3?"), self.engine, scripted, scripted)
        self.assertEqual((row["status"], row["lanes"], row["calls"]), ("answered", ["events"], 1))
        self.assertEqual(row["values"], row["computed"]["values"])
        self.assertEqual(scripted.answer_calls, 0)
        self.assertTrue(all(c["how"] == "event_graph" for c in row["citations"]))

    def test_no_matching_events_falls_back_to_passages(self):
        scripted = ScriptedClient(frame=flat(frame_with(plan("total_hours", code="NOPE"))), answer=NOT_STATED)
        row = coordinator.answer(Q("How many hours of NOPE on AK-3?"), self.engine, scripted, scripted)
        self.assertTrue(row["fallback"])
        self.assertEqual((row["lanes"], row["calls"], row["values"]), (["passages"], 2, []))

    def test_unparseable_frame_answers_from_end_of_well_passages(self):
        scripted = ScriptedClient(frame=None, answer=DEPTH_ANSWER)
        row = coordinator.answer(Q("What total depth did well AK-3 reach?"), self.engine, scripted, scripted)
        self.assertEqual(row["frame"]["kind"], "other")
        self.assertEqual(row["values"], ["1955"])

    def test_exact_mode_with_nothing_in_the_graph_makes_no_answer_call(self):
        scripted = ScriptedClient(frame=flat(FRAME_EOW), answer=DEPTH_ANSWER)
        row = coordinator.answer(Q("What depth did ZZ-9 reach?"), self.engine, scripted, scripted, mode="exact")
        self.assertEqual((row["status"], row["values"], scripted.answer_calls), ("not_found_in_graph", [], 0))
        self.assertIn("sources", row)

    def test_code_reads_the_well_and_several_wells_mean_across_wells(self):
        wrong = flat({"kind": "lookup", "report_type": "end_of_well", "plan": plan("not_answerable", well="AK-9")})
        frame, _ = coordinator.frame_question("Which of AK-3 and 56-32 is deeper?", self.engine, ScriptedClient(wrong, None))
        self.assertEqual(frame["kind"], "across_wells")
        frame, _ = coordinator.frame_question("What depth did AK-3 reach?", self.engine, ScriptedClient(wrong, None))
        self.assertEqual(frame["plan"]["well"], "AK-3")

    def test_a_forced_lane_replaces_the_route(self):
        scripted = ScriptedClient(frame=flat(frame_with(plan("total_hours", code="DRL"))), answer=DEPTH_ANSWER)
        row = coordinator.answer(Q("What total depth did well AK-3 reach?"), self.engine, scripted, scripted, lane="passages")
        self.assertEqual(row["lanes"], ["passages"])
```

`flat(frame)` turns `{"kind", "report_type", "plan": {...}}` into the flat object the model returns. `Q(text)` gives `{"id": "live", "kind": "live", "question": text, "gold": []}`.

- [ ] **Step 2: Run** — expect `ModuleNotFoundError: graphrag.coordinator`.
- [ ] **Step 3: Implement `FRAME_SCHEMA`, `frame_system`, `frame_question` and `route`.**
- [ ] **Step 4: Run** the first two tests and the well test — pass.
- [ ] **Step 5: Implement `answer`.**
- [ ] **Step 6: Run** `python -m unittest tests.test_graphrag_lanes.CoordinatorTests` — 8 pass.
- [ ] **Step 7: Commit** `Track B: the coordinator, one framing call then lanes chosen in code (D-64)`.

---

### Task 6: Pooled runs and K4 version 0.2

**Files:**
- Modify: `graphrag/coordinator.py` (command line), `graphrag/k4.py`, `schemas/k4_answer_record.schema.json`
- Test: `tests/test_graphrag_lanes.py`

**Interfaces:**
- Produces: `python -m graphrag.coordinator answer --questions <set> [<set> ...] --name <run> [--mode exact|allow_fallback] [--k1] [--no-embeddings]`; `pooled(sets: list[str]) -> tuple[list[dict], dict]`; `EXPECTED: dict[str, str]`; `summarize_pool(rows: list[dict]) -> dict`.

- `pooled` loads each set with `data.load_questions`, prefixes every question ID and gold ID with `<set>:`, and adds `set` and `expected` to each question. `EXPECTED` maps `prototype`, `simulated`, `heldout` and `probe` to `end_of_well`; `ak3_daily` and `ak3_daily_heldout` to `daily`; `ak3_events` and `ak3_events_heldout` to `events`.
- A row is **rightly routed** when: expected `events` and `lanes == ["events"]`; expected `daily` and the frame's report type is `daily` (any lane); expected `end_of_well` and the report type is not `daily` and `"events"` is not in `lanes`.
- `summarize_pool` gives, overall and per set: questions, correct, rightly routed, fallbacks, and calls, prompt tokens, completion tokens and seconds per question (frame and answer added).
- The result file `graphrag/results/<name>.json` holds `question_set` (the list), `mode`, `roles` (the role mapping used), the summary and `rows`. `--no-embeddings` sets `Engine.multi_well_retriever` to `"perwell:bm25"`, for a machine without the embedding server.
- **K4 0.2.** `records()` writes `k4_version: "0.2"` and, when a row has them, `pipeline.lanes`, `pipeline.mode` and `pipeline.frame_kind`; `pipeline.base` is `"coordinator"`; `cost.calls` is the row's `calls`; citations of a computed row are its `event_graph` citations. A run that is not a coordinator run still writes version `"0.1"` as before. The schema's `k4_version` accepts both, and `pipeline` gains the three optional properties.

- [ ] **Step 1: Write the failing tests.**

```python
class PooledRunTests(unittest.TestCase):
    def test_pool_prefixes_ids_and_names_the_expected_lane(self):
        questions, gold = coordinator.pooled(["prototype", "probe"])
        self.assertEqual(len(questions), 31 + 9)
        self.assertTrue(all(q["id"].startswith(f"{q['set']}:") and q["expected"] == "end_of_well" for q in questions))
        self.assertTrue(all(g in gold for q in questions for g in q["gold"]))

    def test_routing_is_judged_against_the_source_set(self):
        rows = [{"expected": "events", "lanes": ["events"], "frame": {"report_type": "daily"}},
                {"expected": "events", "lanes": ["passages"], "frame": {"report_type": "daily"}},
                {"expected": "daily", "lanes": ["passages"], "frame": {"report_type": "daily"}},
                {"expected": "end_of_well", "lanes": ["well_facts", "passages"], "frame": {"report_type": "unknown"}},
                {"expected": "end_of_well", "lanes": ["events"], "frame": {"report_type": "daily"}}]
        self.assertEqual([coordinator.rightly_routed(r) for r in rows], [True, False, True, True, False])

class K4VersionTests(unittest.TestCase):
    def test_coordinator_rows_become_version_0_2_records(self):
        # A two-row coordinator result written to a temporary results folder: one computed, one answered from passages.
        records = k4.records(self.run_name)
        self.assertEqual({r["k4_version"] for r in records}, {"0.2"})
        self.assertEqual(records[0]["pipeline"]["lanes"], ["events"])
        self.assertEqual(records[0]["cost"]["calls"], 1)
        for record in records:
            jsonschema.validate(record, self.schema)

    def test_earlier_runs_still_write_version_0_1(self):
        self.assertEqual({r["k4_version"] for r in k4.records("E26_plain_routed")}, {"0.1"})
```

- [ ] **Step 2: Run** — expect failures on `pooled`, `rightly_routed` and the version.
- [ ] **Step 3: Implement `pooled`, `EXPECTED`, `rightly_routed`, `summarize_pool` and `main`** in `graphrag/coordinator.py`; `main` uses `client_for("frame")` and `client_for("answer")`.
- [ ] **Step 4: Change `graphrag/k4.py` and the schema** as described.
- [ ] **Step 5: Run** `python -m unittest tests.test_graphrag_lanes tests.test_graphrag tests.test_contracts` — all pass.
- [ ] **Step 6: Commit** `Track B: pooled coordinator runs and K4 version 0.2`.

The measurement itself is **E33**, on the desktop with the three servers of [next-runs.md](next-runs.md) up, one request at a time:

```powershell
python -m graphrag.coordinator answer --questions prototype simulated heldout ak3_daily ak3_daily_heldout ak3_events ak3_events_heldout --name E33_coordinator_pool
```

Compare per set with spec §8.4: 28, 31 and 23 for the end-of-well sets; 14 of 26 for the held-out daily lookups (17 with the planner in front); 22 of 35 and 19 of 23 for the event sets. Adopt the coordinator only if it matches (D-64).

---

### Task 7: The fact graph as nodes and relationships

**Files:**
- Create: `graphrag/factgraph.py`
- Test: `tests/test_graphrag_lanes.py`

**Interfaces:**
- Produces: `to_graph(facts: list[dict], chunks: list[Chunk]) -> dict` returning `{"nodes": [...], "relationships": [...]}`; `python -m graphrag.factgraph --facts <run> [<run> ...] --pool three --name <name>` writing `graphrag/results/<name>.graph.json`. The facts are validated with `strict=True` before export.

Shapes, following spec §8.5:

- Node: `{"label": str, "key": str, "properties": dict}`. Relationship: `{"type": str, "from": [label, key], "to": [label, key], "properties": dict}`. Both lists are sorted and free of duplicates, so two exports of the same facts are identical.

| Node | Key | Properties |
|---|---|---|
| `Well` | The well's name as `well_names` gives it (the first in sorted order when a fact's `well` holds several forms) | `name` |
| `Document` | `data.document_key(chunk_id)` | `doc_id` |
| `Chunk` | The chunk ID | none |
| `Fact` | `well\|property\|qualifier\|context as sorted JSON\|value` | `property`, `value`, `unit` (if any), `qualifier`, `context` (as JSON text), `source`: `"table_mapping"` when the fact has a `source` table ID, else `"llm"` |
| `HoleSection` | `well\|hole size` | `hole_size_in`; one per fact with property `hole_size` |
| `CasingString` | `well\|casing size` | `casing_size_in`, and `depth`, `weight`, `grade` filled from facts with properties `casing_depth`, `casing_weight`, `casing_grade` whose context has `casing_size_in`, qualifier `actual` only |

| Relationship | From → to |
|---|---|
| `HAS_FACT` | `Well` → `Fact` |
| `FROM` | `Fact` → `Chunk` |
| `DESCRIBED_BY` | `Well` → `Document`, for each document a fact of that well comes from |
| `HAS_CHUNK` | `Document` → `Chunk` |
| `HAS_CASING` | `Well` → `CasingString` |
| `HAS_SECTION` | `Well` → `HoleSection` |

`CASED_WITH` between a hole section and its casing string is left out: no fact today says which casing was set in which hole. Record that in the log entry (Task 8) and in spec §8.5.

- [ ] **Step 1: Write the failing tests.**

```python
class FactGraphTests(unittest.TestCase):
    FACTS = [
        {"chunk": "gdr882_ak3_eowr#c0013", "well": "AK-3", "property": "casing_depth", "qualifier": "actual",
         "context": {"casing_size_in": "8-5/8"}, "value": "40", "source": "gdr882_ak3_eowr#t003"},
        {"chunk": "gdr882_ak3_eowr#c0012", "well": "AK-3", "property": "casing_depth", "qualifier": "planned",
         "context": {"casing_size_in": "8-5/8"}, "value": "40", "source": "gdr882_ak3_eowr#t002"},
        {"chunk": "gdr882_ak3_eowr#c0037", "well": "AK-3", "property": "non_productive_time", "qualifier": "actual",
         "context": None, "value": "115.0"},
    ]

    def test_every_fact_is_a_node_under_its_well_with_its_chunk(self):
        graph = factgraph.to_graph(self.FACTS, [])
        count = lambda label: sum(n["label"] == label for n in graph["nodes"])
        self.assertEqual((count("Well"), count("Fact"), count("Chunk"), count("Document")), (1, 3, 3, 1))
        self.assertEqual(sum(r["type"] == "FROM" for r in graph["relationships"]), 3)
        self.assertEqual(sum(r["type"] == "HAS_FACT" for r in graph["relationships"]), 3)

    def test_planned_and_actual_values_stay_separate_and_name_their_source(self):
        facts = [n for n in factgraph.to_graph(self.FACTS, [])["nodes"] if n["label"] == "Fact"]
        self.assertEqual({n["properties"]["qualifier"] for n in facts}, {"actual", "planned"})
        self.assertEqual({n["properties"]["source"] for n in facts}, {"table_mapping", "llm"})

    def test_casing_string_takes_actual_values_only(self):
        casing = [n for n in factgraph.to_graph(self.FACTS, [])["nodes"] if n["label"] == "CasingString"]
        self.assertEqual(len(casing), 1)
        self.assertEqual(casing[0]["properties"], {"casing_size_in": "8-5/8", "depth": "40"})

    def test_no_dangling_relationships_and_stable_output(self):
        graph = factgraph.to_graph(self.FACTS, [])
        keys = {(n["label"], n["key"]) for n in graph["nodes"]}
        self.assertTrue(all(tuple(r["from"]) in keys and tuple(r["to"]) in keys for r in graph["relationships"]))
        self.assertEqual(graph, factgraph.to_graph(list(reversed(self.FACTS)), []))
```

- [ ] **Step 2: Run** — expect `ModuleNotFoundError: graphrag.factgraph`.
- [ ] **Step 3: Implement `to_graph` and `main`.**
- [ ] **Step 4: Run** `python -m unittest tests.test_graphrag_lanes.FactGraphTests` — 4 pass.
- [ ] **Step 5: Export the real graph.** Run `python -m graphrag.factgraph --facts E22_tables_three --pool three --name E22_fact_graph`. Expected: it prints node and relationship counts per label and type, with no dangling relationship, and writes `graphrag/results/E22_fact_graph.graph.json`. Record the counts in the log (Task 8).
- [ ] **Step 6: Commit** `Track B: the fact graph as nodes and relationships for Neo4j (D-67)`.

---

### Task 8: The local UI on the coordinator, and the record

**Files:**
- Modify: `graphrag/ui.py` (`ask`, `choose_lane`, `sheet_facts`, `fact_sheet_for`), `tests/test_graphrag_ui.py`
- Modify: `graphrag/README.md`, `docs/tracks/B-graphrag/log.md`, `docs/PROJECT_DESIGN.md` (§8.5), `CLAUDE.md` (module table), `docs/tracks/B-graphrag/note-for-track-C-storage.md`

**Interfaces:**
- Consumes: `coordinator.answer`, `lanes.Engine.load`, `client.client_for`.
- Produces: `ui.ask(question: str, lane: str = "auto", mode: str = "allow_fallback") -> dict` with the keys the page reads today (`lane`, `method`, `question`, `status`, `values`, `units`, `evidence`, `citations`, `plan`, `graph_result`, `events`, `prompt_tokens`, `completion_tokens`, `seconds`) plus `lanes`, `frame`, `mode` and `fallback`.

- `lane` values the page sends map as: `auto` → no forced lane; `eowr` → the route for an end-of-well frame; `daily` → `events` with fallback, as today. `method` is a sentence built from `lanes` and `fallback`.
- `choose_lane`, `DAILY_WORDS`, `sheet_facts` and `fact_sheet_for` are removed: the coordinator and `Engine.load` replace them. The engine is loaded once (`lru_cache`).
- The page (`ui.html`) is not changed in this plan: the React application replaces it as the product.

- [ ] **Step 1: Update the tests.** `test_lane_is_chosen_from_the_question` is replaced by:

```python
    def test_live_question_goes_through_the_coordinator(self):
        with patch.object(ui, "endpoint_status", return_value={"up": True, "detail": "test"}), \
                patch("graphrag.client.ModelClient", FakeClient):
            out = ui.ask("What total depth did well AK-3 reach?")
        self.assertIn("passages", out["lanes"])
        self.assertEqual(out["values"], ["1955"])
        self.assertEqual(out["mode"], "allow_fallback")
```

`FakeClient.chat` returns the same answer for every schema, so the framing call parses to nothing useful and the unparseable-frame path of Task 5 is what this test exercises. `test_live_end_of_well_answer_is_cited_and_checked` keeps its assertions.

- [ ] **Step 2: Run** `python -m unittest tests.test_graphrag_ui` — the new test fails.
- [ ] **Step 3: Rewrite `ui.ask`** on `coordinator.answer`, and delete the four helpers.
- [ ] **Step 4: Run** `python -m unittest discover -s tests -p "test_graphrag*.py"` — all pass.
- [ ] **Step 5: Write the record.**
  - `docs/tracks/B-graphrag/log.md`: design-choice entries for the lane interface and evidence shape; the frame schema and its field order; computed results reported by code with no second call; the fact graph export with its node and relationship counts and the missing `CASED_WITH`; K4 version 0.2. Update the "Current state" rows for the coordinator, the graph model and K4.
  - `docs/PROJECT_DESIGN.md` §8.5: `CASED_WITH` is not written yet, and `HAS_CASING` links a well to its casing strings.
  - `graphrag/README.md`: the module table gains `lanes.py`, `coordinator.py` and `factgraph.py`; a "Coordinator" section with the E33 command; the architecture diagram's `KIND` box becomes the framing call.
  - `CLAUDE.md`: the same three rows in the module table.
  - `note-for-track-C-storage.md`: where the fact graph file is and its shape, for Hung's loader.
- [ ] **Step 6: Run** `python -m unittest discover -s tests` — all pass, including the line-ending test.
- [ ] **Step 7: Commit** `Track B: local UI on the coordinator; lanes, coordinator and fact graph recorded`.
