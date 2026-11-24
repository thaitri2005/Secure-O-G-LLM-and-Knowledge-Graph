"""The operations side of the application: what the question log says about how it is doing, and the smoke test a
monitor runs. No server, store or model needed."""
import base64
import contextlib
import importlib.util
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from backend.questions import percentile, statistics

ROOT = Path(__file__).resolve().parents[1]


def entry(status="answered", seconds=10.0, lanes=("well_facts",), **more):
    return {"id": "q", "status": status, "lanes": list(lanes), "fallback": False,
            "cost": {"calls": 2, "prompt_tokens": 3000, "completion_tokens": 100, "seconds": seconds}, **more}


class StatisticsTests(unittest.TestCase):
    def test_percentiles_by_nearest_rank(self):
        self.assertIsNone(percentile([], 0.5))
        self.assertEqual(percentile([5.0], 0.95), 5.0)
        self.assertEqual(percentile([1, 2, 3, 4], 0.5), 2)
        self.assertEqual(percentile(list(range(1, 101)), 0.95), 95)

    def test_rates_lanes_and_costs_of_a_log(self):
        out = statistics([
            entry(seconds=10.0, queue_seconds=0.0), entry(seconds=30.0, queue_seconds=4.0, lanes=("events",)),
            entry("not_found_in_graph", seconds=5.0, lanes=()), entry(seconds=0.0, cached_calls=2),
            entry("error", seconds=60.0, lanes=(), error="ReadTimeout", queue_seconds=1.0),
            entry(seconds=20.0, fallback=True, lanes=("passages",), feedback=[{"verdict": "wrong"}])])
        self.assertEqual(out["questions"], 6)
        self.assertEqual((out["error_rate"], out["not_found_rate"], out["fallback_rate"]), (0.167, 0.167, 0.167))
        self.assertEqual(out["by_error"], {"ReadTimeout": 1})
        self.assertEqual(out["by_lane"]["well_facts"], 2)
        # Timings leave out the failed question and the one answered from the request cache.
        self.assertEqual((out["timed_questions"], out["seconds_p50"], out["seconds_p95"]), (4, 10.0, 30.0))
        self.assertEqual((out["calls_mean"], out["prompt_tokens_mean"], out["queue_seconds_p95"]), (2.0, 3000.0, 4.0))
        self.assertEqual(out["marked_wrong"], 1)

    def test_an_empty_log_has_no_timings(self):
        out = statistics([])
        self.assertEqual((out["questions"], out["seconds_p50"], out["error_rate"]), (0, None, 0.0))


class Application(BaseHTTPRequestHandler):
    """The answers of a deployment, as far as the quick smoke test looks."""
    ready = True

    def do_GET(self):
        if self.headers.get("Authorization") != "Basic " + base64.b64encode(b"team:secret").decode():
            return self.reply(401, b"")
        if self.path == "/":
            return self.reply(200, b"<!doctype html><html></html>")
        if self.path == "/v1/health":
            return self.reply(200, json.dumps({"data": {"wells": 5}, "models": {}}).encode())
        if self.path == "/v1/ready":
            body = {"ready": self.ready, "checks": {"model": "ok" if self.ready else "ConnectError: down"}, "waiting": 0}
            return self.reply(200 if self.ready else 503, json.dumps(body).encode())
        self.reply(404, b"")

    def do_POST(self):
        self.reply(500, b"the quick test must not ask a question")

    def reply(self, status, body):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class SmokeTestTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("smoke_test", ROOT / "deploy/smoke_test.py")
        self.smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.smoke)
        self.server = HTTPServer(("127.0.0.1", 0), Application)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def run_quick(self):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = self.smoke.main(["--url", self.url, "--password", "secret", "--quick"])
        return code, printed.getvalue()

    def test_quick_passes_on_a_ready_deployment_without_asking_a_question(self):
        Application.ready = True
        code, printed = self.run_quick()
        self.assertEqual(code, 0, printed)
        self.assertIn("4 of 4 checks passed", printed)

    def test_quick_fails_and_names_what_is_down(self):
        Application.ready = False
        self.addCleanup(setattr, Application, "ready", True)
        code, printed = self.run_quick()
        self.assertEqual(code, 1)
        self.assertIn("FAIL  ready", printed)
        self.assertIn("ConnectError", printed)


if __name__ == "__main__":
    unittest.main()
