"""The model bench (graphrag.bench, profiles in graphrag.client) against the stand-in server.

scripts/stub_model_server.py runs on a free local port inside each test. It is not a model: these tests prove the
wiring (profiles, checks, resuming, the cache, comparisons), never a score.
"""
import importlib.util
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx

from graphrag import baseline, bench, client, coordinator, events, lanes
from graphrag.client import Endpoint, ModelClient, PrivateDataError

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STUB = _load("stub_model_server", ROOT / "scripts/stub_model_server.py")
RECORD = _load("experiment_record", ROOT / "scripts/experiment_record.py")


class StubServer:
    """The stand-in on a free port. `mode`: "ok", "ignores_schema" (plain text whatever the request), "thinks" (a
    reasoning block and hidden tokens). `fail_after`: chat calls after that many get HTTP 503. `props`: answers
    llama.cpp's /props with it."""

    def __init__(self, mode: str = "ok", fail_after: int | None = None, props: dict | None = None):
        self.mode, self.fail_after, self.props, self.chat_calls = mode, fail_after, props, 0
        outer = self

        class Handler(STUB.QuietHandler):
            def do_GET(self):  # noqa: N802
                if self.path.rstrip("/") == "/props" and outer.props:
                    self._send(200, outer.props)
                else:
                    super().do_GET()

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if not self.path.endswith("/chat/completions"):
                    self._send(200, STUB.embedding_response(body))
                    return
                outer.chat_calls += 1
                if outer.fail_after is not None and outer.chat_calls > outer.fail_after:
                    self._send(503, {"error": {"message": "the machine was switched off"}})
                    return
                reply = STUB.chat_response(body)
                message = reply["choices"][0]["message"]
                if outer.mode == "ignores_schema":
                    message["content"] = "Sure. The well reached a total depth of 1,955 ft."
                elif outer.mode == "thinks":
                    message["reasoning_content"] = "Let me think about the passages one by one."
                    reply["usage"]["completion_tokens"] += 600
                self._send(200, reply)

        self.server = STUB.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Sandbox(unittest.TestCase):
    """Results, cache and profiles in a temporary folder; no environment variable leaks in or out."""

    def setUp(self):
        # Inside the repository, as the commands print their run files relative to it; data/interim/ is ignored.
        (ROOT / "data/interim").mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=ROOT / "data/interim", prefix="test_bench_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.results = self.root / "results"
        self.results.mkdir()
        for target in (baseline, coordinator, events, lanes):
            patcher = patch.object(target, "RESULTS", self.results)
            patcher.start()
            self.addCleanup(patcher.stop)
        # One connection pool for the test's calls: a new HTTP client per call costs most of a second here.
        session = httpx.Client()
        self.addCleanup(session.close)
        for patcher in (patch.object(client, "CACHE", self.root / "cache"), patch.dict(client._REGISTERED, clear=True),
                        patch.dict(os.environ), patch("graphrag.client.httpx.post", session.post)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("GRAPHRAG_PROFILE", None)

    def server(self, **kwargs) -> StubServer:
        server = StubServer(**kwargs)
        self.addCleanup(server.close)
        return server

    def profile(self, name: str, url: str, **fields) -> str:
        path = self.root / f"{name}.json"
        path.write_text(json.dumps({"base_url": url, "hosted": False, "model": "qwen3-8b", "context": 32768, **fields}),
                        encoding="utf-8")
        return str(path)

    def quiet(self, function, *args, **kwargs):
        with redirect_stdout(io.StringIO()):
            return function(*args, **kwargs)


class ProfileTests(Sandbox):
    def test_a_profile_name_gives_its_endpoint_model_and_own_cache(self):
        endpoint, model = client.resolve("qwen3-8b.local")
        self.assertEqual((endpoint.name, endpoint.base_url, endpoint.hosted, model),
                         ("qwen3-8b.local", "http://127.0.0.1:8080/v1", False, "qwen3-8b"))
        self.assertEqual(endpoint.cache_tag, "qwen3-8b.local|Qwen3-8B-Q4_K_M.gguf")

    def test_the_hosted_profile_turns_thinking_off_in_the_request(self):
        endpoint, model = client.resolve("qwen3-8b.openrouter")
        self.assertTrue(endpoint.hosted)
        self.assertEqual(endpoint.api_key_env, "OPENROUTER_API_KEY")
        self.assertEqual(endpoint.request["reasoning"], {"enabled": False})
        self.assertEqual(model, "qwen/qwen3-8b")

    def test_endpoint_model_is_the_endpoint_of_the_file_as_it_was(self):
        endpoint, model = client.resolve("local-llama:qwen3-8b")
        self.assertEqual(endpoint, client.load_endpoints()["local-llama"])
        self.assertEqual(model, "qwen3-8b")
        # A model ID may itself hold a colon, as OpenRouter's variants do.
        self.assertEqual(client.resolve("openrouter:qwen/qwen3-8b:free")[1], "qwen/qwen3-8b:free")

    def test_a_profile_file_by_path_and_every_endpoint_name_still_work(self):
        spec = self.profile("my-model", "http://127.0.0.1:9/v1")
        endpoint, _ = client.resolve(spec)
        self.assertEqual((endpoint.name, endpoint.hosted), ("my-model", False))
        endpoints = client.load_endpoints()
        self.assertEqual(endpoints[spec].name, "my-model")
        self.assertEqual(endpoints["qwen3-8b.local"].name, "qwen3-8b.local")
        self.assertIn("local-embed", endpoints)
        with self.assertRaises(KeyError):
            endpoints["no-such-endpoint"]
        # `get`, as the UI's endpoint status uses it, finds profiles too.
        self.assertEqual(endpoints.get("qwen3-8b.local").base_url, "http://127.0.0.1:8080/v1")
        self.assertIsNone(endpoints.get("no-such-endpoint"))

    def test_the_deployment_roles_for_openrouter_use_the_profile(self):
        roles = client.load_roles(ROOT / "deploy/models/roles.openrouter.json")
        made = client.client_for("answer", roles, cache_dir=None)
        self.assertEqual((made.endpoint.base_url, made.model), ("https://openrouter.ai/api/v1", "qwen/qwen3-8b"))
        self.assertTrue(made.endpoint.hosted)
        self.assertEqual(made.endpoint.request["reasoning"], {"enabled": False})
        self.assertEqual(roles["embed"], {"endpoint": "local-embed", "model": "qwen3-embedding-0.6b"})

    def test_an_unknown_profile_names_the_ones_there_are(self):
        with self.assertRaises(FileNotFoundError) as caught:
            client.load_profile("no-such-model")
        self.assertIn("qwen3-8b.local", str(caught.exception))

    def test_a_profile_cannot_make_a_hosted_endpoint_local(self):
        spec = str(self.root / "sneaky.json")
        Path(spec).write_text(json.dumps({"endpoint": "openrouter", "hosted": False, "model": "m"}), encoding="utf-8")
        endpoint, model = client.resolve(spec)
        self.assertTrue(endpoint.hosted)
        with patch("graphrag.client.httpx.post") as post, self.assertRaises(PrivateDataError):
            ModelClient(endpoint, model, cache_dir=None).chat([{"role": "user", "content": "x"}], data_class="private")
        post.assert_not_called()

    def test_another_machine_is_hosted_unless_reached_on_this_one(self):
        with self.assertRaises(ValueError):
            client.resolve(self.profile("remote", "http://203.0.113.7:8080/v1"))
        spec = str(self.root / "remote-hosted.json")
        Path(spec).write_text(json.dumps({"base_url": "http://203.0.113.7:8080/v1", "model": "m"}), encoding="utf-8")
        self.assertTrue(client.resolve(spec)[0].hosted)

    def test_graphrag_profile_serves_the_roles_it_lists(self):
        os.environ["GRAPHRAG_PROFILE"] = "qwen3-8b.openrouter"
        roles = client.load_roles()
        self.assertEqual(roles["answer"], {"endpoint": "qwen3-8b.openrouter", "model": "qwen/qwen3-8b",
                                           "profile": "qwen3-8b.openrouter"})
        self.assertEqual(roles["embed"]["endpoint"], "local-embed")
        made = client.client_for("frame", roles, cache_dir=None)
        self.assertTrue(made.endpoint.hosted)
        self.assertEqual(made.model, "qwen/qwen3-8b")

    def test_the_roles_file_may_name_a_profile_for_one_role(self):
        path = self.root / "roles.json"
        path.write_text(json.dumps({"frame": {"endpoint": "local-llama", "model": "qwen3-8b"},
                                    "extract": {"profile": "qwen3-4b.local"}}), encoding="utf-8")
        roles = client.load_roles(path)
        self.assertEqual(roles["frame"], {"endpoint": "local-llama", "model": "qwen3-8b"})
        self.assertEqual(client.client_for("extract", roles, cache_dir=None).endpoint.base_url, "http://127.0.0.1:8082/v1")

    def test_the_request_fields_are_sent(self):
        endpoint = Endpoint("p", "http://127.0.0.1:9/v1", False, request={"reasoning": {"enabled": False}})
        reply = httpx.Response(200, request=httpx.Request("POST", "http://x"), json={
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "choices": [{"message": {"content": "hi"}}]})
        with patch("graphrag.client.httpx.post", return_value=reply) as post:
            ModelClient(endpoint, "m", cache_dir=None).chat([{"role": "user", "content": "x"}])
        self.assertEqual(post.call_args.kwargs["json"]["reasoning"], {"enabled": False})


class CacheTests(Sandbox):
    def test_the_cache_never_crosses_models_or_profiles(self):
        server = self.server()
        messages = [{"role": "user", "content": "What total depth did AK-3 reach?"}]
        plain = Endpoint("local-llama", server.url, False)
        tagged = Endpoint("a", server.url, False, cache_tag="a|Qwen3-8B-Q4_K_M.gguf")
        other = Endpoint("b", server.url, False, cache_tag="b|Qwen3-8B-Q8_0.gguf")
        for endpoint, model in ((plain, "qwen3-8b"), (plain, "qwen3-4b"), (tagged, "qwen3-8b"), (other, "qwen3-8b")):
            self.assertFalse(ModelClient(endpoint, model).chat(messages).cached)
        self.assertEqual(server.chat_calls, 4)
        again = ModelClient(tagged, "qwen3-8b").chat(messages)
        self.assertTrue(again.cached)
        self.assertEqual(server.chat_calls, 4)

    def test_a_cached_call_keeps_what_it_cost_when_made(self):
        server = self.server()
        endpoint = Endpoint("p", server.url, False, price_in=1.0, price_out=1.0, cache_tag="p|")
        first = ModelClient(endpoint, "qwen3-8b").chat([{"role": "user", "content": "x y z"}])
        later = ModelClient(endpoint, "qwen3-8b")
        second = later.chat([{"role": "user", "content": "x y z"}])
        self.assertEqual((second.seconds, second.cost_usd), (0.0, 0.0))
        self.assertEqual((second.cached_seconds, second.cached_cost_usd), (first.seconds, first.cost_usd))
        summary = later.ledger.summary()
        self.assertEqual((summary["cached_calls"], summary["cached_cost_usd"]), (1, round(first.cost_usd, 6)))


class CheckTests(Sandbox):
    def checked(self, spec: str) -> dict:
        return {row["check"]: row for row in bench.check(spec)}

    def test_a_server_that_follows_the_schemas_passes(self):
        server = self.server()
        spec = self.profile("good", server.url)
        rows = self.checked(spec)
        self.assertTrue(all(r["ok"] is not False for r in rows.values()), rows)
        for name in ("endpoint answers", "model ID exists", "JSON schema: framing", "JSON schema: answer",
                     "reasoning-size prompt fits", "thinking is off", "tokens are reported"):
            self.assertIs(rows[name]["ok"], True, name)
        self.assertEqual(server.chat_calls, 3)
        self.assertIn("stand-in server", rows)  # its replies are labelled, and the check says so
        self.assertEqual(self.quiet(bench.print_check, spec, list(rows.values())), 0)

    def test_a_server_that_ignores_the_schema_fails_with_what_to_change(self):
        spec = self.profile("loose", self.server(mode="ignores_schema").url)
        rows = self.checked(spec)
        for name in ("JSON schema: framing", "JSON schema: answer", "reasoning-size prompt fits"):
            self.assertIs(rows[name]["ok"], False, name)
        self.assertIn("response_format", rows["JSON schema: framing"]["fix"])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(bench.print_check(spec, list(rows.values())), 1)
        self.assertIn("required check(s) failed", output.getvalue())
        with self.assertRaises(SystemExit) as caught:
            self.quiet(bench.main, ["check", spec])
        self.assertEqual(caught.exception.code, 1)

    def test_a_model_that_thinks_fails(self):
        rows = self.checked(self.profile("thinker", self.server(mode="thinks").url))
        self.assertIs(rows["thinking is off"]["ok"], False)
        self.assertIn("enable_thinking", rows["thinking is off"]["fix"])
        self.assertIs(rows["JSON schema: answer"]["ok"], True)

    def test_a_server_that_is_down_fails_first_and_alone(self):
        rows = bench.check(self.profile("down", f"http://127.0.0.1:{free_port()}/v1"))
        self.assertEqual([(r["check"], r["ok"]) for r in rows], [("endpoint answers", False)])
        self.assertIn("start the model server", rows[0]["fix"])

    def test_an_unknown_model_id_fails(self):
        rows = self.checked(self.profile("typo", self.server().url, model="qwen3-8b-typo"))
        self.assertIs(rows["model ID exists"]["ok"], False)

    def test_a_server_running_another_model_file_fails(self):
        props = {"model_path": "/models/Qwen3-8B-Q8_0.gguf", "total_slots": 1, "build_info": "b12015",
                 "default_generation_settings": {"n_ctx": 32768}}
        rows = self.checked(self.profile("filed", self.server(props=props).url, file="Qwen3-8B-Q4_K_M.gguf"))
        self.assertIs(rows["model file"]["ok"], False)
        self.assertIs(rows["server context"]["ok"], True)


class RunTests(Sandbox):
    def test_the_quick_suite_writes_its_run_and_record(self):
        server = self.server()
        spec = self.profile("good", server.url)
        manifest = self.quiet(bench.run, spec, "quick", name="t")
        self.assertEqual([s["status"] for s in manifest["steps"]], ["done"])
        self.assertEqual(server.chat_calls, 31)
        result = json.loads((self.results / "t_quick_prototype.json").read_text(encoding="utf-8"))
        self.assertEqual((result["questions"], result["endpoint"], result["model"]), (31, spec, "qwen3-8b"))
        record = json.loads((self.results / "t.bench.json").read_text(encoding="utf-8"))
        self.assertEqual(record["profile"]["name"], "good")
        self.assertEqual((record["totals"]["calls"], record["totals"]["cached_calls"]), (31, 0))
        self.assertTrue(record["date"] and record["finished"] and record["one_request_at_a_time"])

    def test_a_stopped_run_resumes_without_paying_again(self):
        server = self.server(fail_after=10)
        spec = self.profile("good", server.url)
        with self.assertRaises(SystemExit) as caught:
            self.quiet(bench.run, spec, "quick", name="t")
        self.assertIn("Run the same command again", str(caught.exception))
        record = json.loads((self.results / "t.bench.json").read_text(encoding="utf-8"))
        self.assertEqual(record["steps"][0]["status"], "stopped")
        server.fail_after, before = None, server.chat_calls
        manifest = self.quiet(bench.run, spec, "quick", name="t")
        self.assertEqual(server.chat_calls - before, 21)  # questions 11 to 31 only
        self.assertEqual((manifest["totals"]["calls"], manifest["totals"]["cached_calls"]), (31, 10))
        # A finished run run again, from the command line, pays for nothing and repeats nothing.
        self.quiet(bench.main, ["run", spec, "--name", "t"])
        self.assertEqual(server.chat_calls - before, 21)

    def test_another_profile_on_the_same_server_pays_again(self):
        server = self.server()
        self.quiet(bench.run, self.profile("first", server.url), "quick")
        self.quiet(bench.run, self.profile("second", server.url), "quick")
        self.assertEqual(server.chat_calls, 62)
        self.assertTrue((self.results / "bench_second_quick.bench.json").is_file())

    def test_a_run_is_resumed_only_with_the_same_model_and_options(self):
        server = self.server()
        self.quiet(bench.run, self.profile("first", server.url), "quick", name="t")
        with self.assertRaises(SystemExit) as caught:
            self.quiet(bench.run, self.profile("second", server.url), "quick", name="t")
        self.assertIn("different", str(caught.exception))

    def test_a_server_running_another_model_file_is_refused(self):
        props = {"model_path": "C:\\models\\Qwen3-8B-Q8_0.gguf", "default_generation_settings": {"n_ctx": 32768}}
        server = self.server(props=props)
        with self.assertRaises(SystemExit):
            self.quiet(bench.run, self.profile("filed", server.url, file="Qwen3-8B-Q4_K_M.gguf"), "quick")
        self.assertEqual(server.chat_calls, 0)

    def test_the_served_file_and_build_join_the_cache_tag(self):
        props = {"model_path": "/m/Qwen3-8B-Q4_K_M.gguf", "build_info": "b12015", "default_generation_settings": {}}
        server = self.server(props=props)
        spec = self.profile("filed", server.url, file="Qwen3-8B-Q4_K_M.gguf")
        self.quiet(bench.run, spec, "quick", name="a")
        self.assertEqual(client._REGISTERED[spec].cache_tag, "filed|Qwen3-8B-Q4_K_M.gguf@b12015")
        server.props["build_info"] = "b13000"  # a llama.cpp upgrade is measured again
        self.quiet(bench.run, spec, "quick", name="b")
        self.assertEqual(server.chat_calls, 62)

    def test_a_profile_that_serves_no_answer_role_is_refused(self):
        with self.assertRaises(SystemExit):
            bench.run(self.profile("extractor", "http://127.0.0.1:9/v1", roles=["extract"]))

    def test_a_full_run_without_the_daily_reports_stops_before_its_first_call(self):
        server = self.server()
        spec = self.profile("good", server.url)
        with patch.object(events, "inputs", side_effect=FileNotFoundError("no corpus")), \
                self.assertRaises(SystemExit) as caught:
            self.quiet(bench.run, spec, "full", no_embeddings=True)
        self.assertIn("--k1", str(caught.exception))
        self.assertEqual(server.chat_calls, 0)
        self.assertFalse(list(self.results.glob("*.bench.json")))

    def test_the_coordinator_step_runs_on_the_profile_and_lines_up_with_its_own_baseline(self):
        server = self.server()
        spec = self.profile("good", server.url)
        self.quiet(bench.run, spec, "quick", name="t")
        step = {"id": "coordinator", "experiment": "E33", "command": "coordinator", "run": "c_coordinator",
                "argv": ["answer", "--questions", "prototype", "--no-embeddings", "--name", "c_coordinator"],
                "status": "pending"}
        with patch.object(bench, "steps", return_value=[step]):
            manifest = self.quiet(bench.run, spec, "quick", name="c")
        # A framing call and an answer call per question; an answer prompt the quick run already sent (the same
        # passages) comes from this profile's cache.
        self.assertEqual(manifest["totals"]["calls"], 62)
        self.assertEqual(server.chat_calls - 31 + manifest["totals"]["cached_calls"], 62)
        result = json.loads((self.results / "c_coordinator.json").read_text(encoding="utf-8"))
        self.assertEqual(result["roles"]["answer"], {"endpoint": spec, "model": "qwen3-8b", "profile": "good"})
        self.assertNotIn("GRAPHRAG_PROFILE", os.environ)
        output = bench.compare(["t", "c"])
        self.assertNotIn("Not comparable", output)
        self.assertIn("Coordinator against the hand-routed scores of the same profile", output)
        self.assertRegex(output, r"\| prototype \| c \| \d+/31 \(t\) \| \d+/31 \| [+-]\d+ \|")
        self.assertIn("Answered by the stand-in server", output)

    def test_the_full_suite_is_the_existing_commands(self):
        planned = bench.steps("full", "n", "p", "m", k1=True, no_embeddings=True)
        self.assertEqual([s["id"] for s in planned],
                         ["hand/prototype", "hand/simulated", "hand/heldout", "hand/ak3_daily", "hand/ak3_daily_heldout",
                          "hand/ak3_events", "hand/ak3_events_heldout", "coordinator", "k1/prototype", "reasoning"])
        by_id = {s["id"]: s for s in planned}
        prototype = by_id["hand/prototype"]["argv"]
        self.assertIn("perwell:bm25", prototype)
        self.assertNotIn("--sheet-properties", prototype)
        self.assertEqual(by_id["hand/ak3_daily"]["argv"][2], "k1_daily")
        self.assertEqual(by_id["hand/ak3_events"]["command"], "events")
        pooled = by_id["coordinator"]["argv"]
        self.assertEqual(pooled[pooled.index("--questions") + 1:pooled.index("--k1")],
                         list(bench.EOW_SETS + bench.DAILY_SETS + bench.EVENT_SETS))
        self.assertIn(bench.PROBE, by_id["reasoning"]["argv"])
        self.assertTrue(all(s["argv"][-2:] == ["--name", s["run"]] for s in planned))
        with_embeddings = bench.steps("full", "n", "p", "m", k1=False, no_embeddings=False)
        self.assertNotIn("k1/prototype", [s["id"] for s in with_embeddings])
        self.assertIn(bench.FUSION, with_embeddings[0]["argv"])
        self.assertEqual(with_embeddings[3]["argv"][2], "ak3_daily")


def ledger(calls: int, prompt: int, completion: int, seconds: float = 1.0, cost: float = 0.0) -> dict:
    return {"calls": calls, "cached_calls": 0, "invalid_json": 0, "prompt_tokens": prompt,
            "completion_tokens": completion, "seconds": seconds, "cost_usd": cost, "cached_seconds": 0.0,
            "cached_cost_usd": 0.0, "models": [], "providers": []}


def answer_rows(correct: int, total: int, **extra) -> list[dict]:
    return [{"id": f"q{i}", "correct": i < correct, "status": "answered", "no_wrong_values": i < correct + 1,
             "prompt_tokens": 100, "completion_tokens": 10, "seconds": 0.1, **extra} for i in range(total)]


class CompareTests(Sandbox):
    def write_run(self, name: str, profile: dict, results: dict[str, dict]) -> None:
        steps = []
        for step_id, result in results.items():
            run = f"{name}_{step_id.replace('/', '_')}"
            (self.results / f"{run}.json").write_text(json.dumps(result), encoding="utf-8")
            steps.append({"id": step_id, "run": run, "status": "done", "command": "baseline", "argv": []})
        manifest = {"name": name, "profile": {"roles": ["frame", "answer"], **profile}, "date": "2026-11-24",
                    "model": "m", "endpoint": {"base_url": "http://x/v1"}, "server": {}, "identity": {"options": {}},
                    "steps": steps, "totals": {"providers": []}}
        (self.results / f"{name}.bench.json").write_text(json.dumps(manifest), encoding="utf-8")

    def hand(self, correct: int) -> dict:
        return {"question_set": "prototype", "pool": "three", "retriever": "wells:bm25", "fact_sheet": None,
                "questions": 4, "rows": answer_rows(correct, 4), "cost": ledger(4, 400, 40)}

    def coordinated(self, correct: int) -> dict:
        rows = [dict(row, set="prototype", calls=2, frame_prompt_tokens=50, frame_completion_tokens=5, frame_seconds=0.1,
                     rightly_routed=True, fallback=False) for row in answer_rows(correct, 4)]
        return {"question_set": ["prototype"], "retriever": "coordinator", "pool": "bundle and corpus release",
                "questions": 4, "rows": rows, "cost": {"frame": ledger(4, 200, 20), "answer": ledger(4, 400, 40)}}

    def test_runs_of_different_profiles_are_never_lined_up(self):
        self.write_run("local", {"name": "qwen3-8b.local", "compare_as": "local-llama:qwen3-8b", "hosted": False},
                       {"hand/prototype": self.hand(3), "coordinator": self.coordinated(4)})
        self.write_run("hosted", {"name": "qwen3-8b.openrouter", "hosted": True},
                       {"coordinator": self.coordinated(2)})
        output = bench.compare(["local", "hosted"])
        self.assertIn("Not comparable", output)
        self.assertEqual(output.count("### "), 2)
        local, hosted = output.split("### qwen3-8b.openrouter")
        self.assertIn("| prototype | local | 3/4 (local) | 4/4 | +1 | 4/4 |", local)
        # The hosted coordinator is not judged against the local hand-routed score.
        self.assertIn("| prototype | hosted | not run | 2/4 | - |", hosted)
        self.assertIn("No hand-routed run from this profile for prototype", hosted)
        self.assertNotIn("(local)", hosted)

    def test_a_local_profile_lines_up_with_the_recorded_runs_of_the_same_model(self):
        self.write_run("local", {"name": "qwen3-8b.local", "compare_as": "local-llama:qwen3-8b", "hosted": False},
                       {"coordinator": self.coordinated(4)})
        recorded = dict(self.hand(3), cost=dict(ledger(4, 400, 40), models=["local-llama:qwen3-8b"]))
        (self.results / "E99_recorded.json").write_text(json.dumps(recorded), encoding="utf-8")
        output = bench.compare(["local", "E99_recorded"])
        self.assertNotIn("Not comparable", output)
        self.assertIn("3/4 (E99_recorded)", output)
        self.assertIn("| 4/4 | +1 |", output)

    def test_cost_per_question_comes_from_the_ledgers(self):
        self.write_run("local", {"name": "p", "hosted": False}, {"hand/prototype": self.hand(3)})
        output = bench.compare(["local"])
        self.assertIn("| prototype | local (wells:bm25, three) | 3/4 | 0 | 1.0 | 100 | 10 | 0.25 | 0.000000 |", output)


class RecordTests(Sandbox):
    def test_a_draft_record_has_the_tables_and_leaves_the_prose_blank(self):
        server = self.server()
        self.quiet(bench.run, self.profile("good", server.url), "quick", name="t")
        register = (ROOT / "docs/experiments/README.md").read_bytes()
        out = self.root / "E99-draft.md"
        self.quiet(RECORD.main, ["E99", "t", "--title", "Wiring", "--out", str(out)])
        text = out.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# E99: Wiring"))
        for part in ("| **Date** |", "| **Models** |", "## Results", "| prototype | t (bm25, ak3) |", "## Cost",
                     "TO WRITE (a person):", "stand-in server", "## How it was run",
                     "#   quick/prototype: python -m graphrag.baseline answer --pool ak3"):
            self.assertIn(part, text)
        self.assertEqual((ROOT / "docs/experiments/README.md").read_bytes(), register)
        with self.assertRaises(SystemExit):
            self.quiet(RECORD.main, ["E99", "t", "--out", str(out)])


if __name__ == "__main__":
    unittest.main()
