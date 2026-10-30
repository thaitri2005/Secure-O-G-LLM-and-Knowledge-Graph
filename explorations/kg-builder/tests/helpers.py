"""Shared subprocess, fixture, metric-key, and fake LM Studio helpers for tests."""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PY_CORE = PROJECT_ROOT / ".venvs" / "kggen" / "Scripts" / "python.exe"
PY_EDC = PROJECT_ROOT / ".venvs" / "edc" / "Scripts" / "python.exe"
RECORDED = {"kggen_showcase": PROJECT_ROOT / "data/fixtures/llm/showcase_kggen.jsonl", "edc_webnlg10": PROJECT_ROOT / "data/fixtures/llm/webnlg10_edc.jsonl", "kggen_mine3": PROJECT_ROOT / "data/fixtures/llm/mine3_kggen.jsonl"}
LIVE_FIXTURE = PROJECT_ROOT / "data/fixtures/llm/showcase_webnlg10_kggen.jsonl"
TWOWIKI_QA_FIXTURE = PROJECT_ROOT / "data/fixtures/llm/twowiki10_kggen_qa.jsonl"
BASELINE_REPLAY_LOGS = ["data/fixtures/llm/webnlg10_edc.jsonl", "data/fixtures/llm/mine3_kggen.jsonl",
                 "data/fixtures/llm/showcase_kggen.jsonl", "data/fixtures/llm/showcase_webnlg10_kggen.jsonl"]
METRIC_KEYS = set("docs chunks failed_chunks mentions candidates duplicate_candidates grounding surfaces_non_literal entities entities_literal er_reduction ambiguous_acronyms canon statements_accepted statements_rejected rejected_by_reason temporal_statements llm net_blocked stage_seconds judge_unparsed judge_errors".split())
METRIC_KEYS.add("ground_rules")
METRIC_KEYS.update(("statements_flagged", "flagged_by_reason"))
SENTENCE_GROUNDING = ["ground.mode=sentence", "resolve.number_guard=false", "validate.mode=strict",
             "judge.version=v1", "judge.max_tokens=8"]
EXACT_LINKING_QA = ["qa.seed_linking=exact", "qa.fact_order=confidence"]
WINDOW_GROUNDING = ["ground.mode=window", "resolve.number_guard=true", "validate.mode=soft",
      "judge.version=v2", "judge.max_tokens=32"]
ROBUST_LINKING_QA = ["qa.seed_linking=robust", "qa.fact_order=relevance"]


def sets(items: list[str]) -> list[str]:
    return [part for item in items for part in ("--set", item)]


def assert_graph_equivalent(test, replayed: Path, recorded: Path):
    """Compare all graph fields, mapping only declared provenance versions."""
    mapping = json.loads((PROJECT_ROOT / "tests/fixtures/bsee_guided/extractor_version_mapping.json").read_text())
    values = set(mapping) | set(mapping.values())
    affected = False
    def mapped(value):
        nonlocal affected
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key == "extractor_version" and isinstance(item, str) and item in values:
                    affected = True
                    result[key] = mapping.get(item, item)
                else:
                    result[key] = mapped(item)
            return result
        if isinstance(value, list):
            return [mapped(item) for item in value]
        return value
    left = mapped(json.loads(replayed.read_bytes()))
    right = mapped(json.loads(recorded.read_bytes()))
    if affected:
        canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        test.assertEqual(canonical(left), canonical(right), str(recorded))
    else:
        test.assertEqual(replayed.read_bytes(), recorded.read_bytes(), str(recorded))


def assert_expected_artifact(test, path, entry):
    """Check complete synthetic output bytes and their independent pinned digest."""
    expected = entry["text"].encode()
    test.assertEqual(hashlib.sha256(expected).hexdigest(), entry["sha256"])
    test.assertEqual(path.read_bytes(), expected)
    test.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])


def replay_set(*extra: str) -> list[str]:
    """Keep fake-server tests independent of later live captures."""
    return ["--set", "llm.replay_logs=[" + ", ".join([*BASELINE_REPLAY_LOGS, *extra]) + "]"]


def run_kgb(args: list[str], timeout: int = 900, test_id: str | None = None, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Run the supported CLI with project-local environment values."""
    full = list(args)
    if full and (full[0] in {"build", "run", "induce", "ablate"} or full[:2] == ["eval", "qa"]):
        full += ["--set", f"llm.cache_path=.cache/tmp/tests/{test_id or 'default'}/no_cache.jsonl"]
    env = os.environ.copy()
    for raw in (PROJECT_ROOT / "configs/runtime/onprem.env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = str(PROJECT_ROOT / value[2:]) if value.startswith("./") else value
    env.update({"PYTHONPATH": str(PROJECT_ROOT / "src"), "PYTHONHASHSEED": "0"})
    if env_extra:
        env.update(env_extra)
    return subprocess.run([str(PY_CORE), "-m", "kgbuilder", *full], cwd=PROJECT_ROOT, env=env, text=True, encoding="utf-8", capture_output=True, timeout=timeout)


def clean_dir(path: Path) -> Path:
    """Remove and recreate a test directory."""
    path = path.resolve()
    if not path.is_relative_to(PROJECT_ROOT) or path == PROJECT_ROOT:
        raise ValueError(f"test directory must stay within the project: {path}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def fake_lmstudio(replies, metadata=None):
    """Serve deterministic completion replies on an ephemeral loopback port."""
    received = []
    values = list(replies) if not callable(replies) else replies
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            body = json.dumps(metadata(self.path) if metadata is not None else {"data": [{"id": "qwen3.6-35b-a3b"}]}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            received.append((self.path, body))
            text = values(body) if callable(values) else (values.pop(0) if values else "")
            status = text if isinstance(text, int) else 200
            reply = {"error": {"message": f"fake {status}"}} if isinstance(text, int) else {
                "choices": [{"text": text, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": len(text.split())}}
            out = json.dumps(reply).encode()
            self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f"http://127.0.0.1:{server.server_address[1]}/v1", received
    finally: server.shutdown(); server.server_close()


@contextmanager
def fake_vllm(replies, api_key: str = "test-key", model: str = "qwen3.6-35b-a3b-fp8", max_model_len: int = 16384):
    """Serve authenticated vLLM metadata and both completion modes on loopback."""
    received = []
    values = list(replies) if not callable(replies) else replies
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def reply(self, status, body):
            raw = json.dumps(body).encode("utf-8")
            self.send_response(status); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def authorized(self):
            if self.headers.get("Authorization") == "Bearer " + api_key: return True
            self.reply(401, {"error": {"message": "unauthorized"}})
            return False
        def do_GET(self):
            if not self.authorized(): return
            received.append((self.path, None, self.headers.get("Authorization")))
            if self.path != "/v1/models": return self.reply(404, {"error": {"message": "unknown endpoint"}})
            self.reply(200, {"object": "list", "data": [{"id": model, "object": "model", "max_model_len": max_model_len}]})
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            received.append((self.path, body, self.headers.get("Authorization")))
            if not self.authorized(): return
            if self.path not in {"/v1/completions", "/v1/chat/completions"}: return self.reply(404, {"error": {"message": "unknown endpoint"}})
            value = values(body) if callable(values) else (values.pop(0) if values else "")
            choice = {"text": value} if self.path == "/v1/completions" else {"message": {"role": "assistant", "content": value}}
            self.reply(200, {"choices": [{**choice, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": len((value or "").split())}})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f"http://127.0.0.1:{server.server_address[1]}/v1", received
    finally: server.shutdown(); server.server_close(); thread.join()
