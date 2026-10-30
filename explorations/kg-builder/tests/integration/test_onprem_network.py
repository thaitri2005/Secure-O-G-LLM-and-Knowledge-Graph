"""Loopback guard behavior and environment containment tests."""
from __future__ import annotations
import json
import os
import socket
import subprocess
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from kgbuilder.runtime.onprem import blocked_count, guard_network, is_loopback, require_loopback_url
from helpers import PROJECT_ROOT, LIVE_FIXTURE, PY_CORE, PY_EDC, clean_dir, run_kgb
from kgbuilder.core.config import KgbError
from kgbuilder.build.pipeline import check_health
from kgbuilder.core.text import write_jsonl


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.saved = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo)
        self.tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests" / self._testMethodName)
    def tearDown(self): socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = self.saved
    def test_guard_blocks_external(self):
        p = guard_network(self.tmp / "net.jsonl")
        with self.assertRaises(ConnectionRefusedError): socket.create_connection(("93.184.216.34", 80), timeout=0.1)
        with self.assertRaises(ConnectionRefusedError): socket.getaddrinfo("example.com", 80)
        self.assertEqual(blocked_count(p), 2)
    def test_guard_truncates_stale_log(self):
        p = self.tmp / "a.jsonl"; p.write_text('{"allowed":false}\n', encoding="utf-8")
        guard_network(p); self.assertEqual(blocked_count(p), 0)
        q = self.tmp / "b.jsonl"; guard_network(q); guard_network(p)
        with self.assertRaises(ConnectionRefusedError): socket.getaddrinfo("example.com", 80)
        self.assertEqual(blocked_count(p), 1)
    def test_helpers(self):
        self.assertTrue(is_loopback("127.0.0.5")); self.assertFalse(is_loopback("192.168.1.5"))
        with self.assertRaisesRegex(ValueError, "llm.base_url"): require_loopback_url("http://api.openai.com/v1", "llm.base_url", ("http",))

    def child_env(self, extra=None):
        env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src"), "PYTHONHASHSEED": "0",
               "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        if extra:
            env.update(extra)
        return env

    def worker_selftest(self, env=None):
        net = self.tmp / "net_edc.jsonl"
        result = subprocess.run([str(PY_EDC), "-m", "kgbuilder.build.refine.edc_worker",
                                 "--selftest", "--net-log", str(net)],
                                cwd=self.tmp, env=self.child_env(env), capture_output=True,
                                text=True, encoding="utf-8", timeout=180)
        (self.tmp / "worker_stdout.txt").write_text(result.stdout, encoding="utf-8")
        (self.tmp / "worker_stderr.txt").write_text(result.stderr, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(net.is_file())
        self.assertEqual(blocked_count(net), 0, net.read_text(encoding="utf-8"))

    def test_imports_offline(self):
        code = """
from pathlib import Path
from kgbuilder.runtime.onprem import load_env, guard_network, blocked_count
load_env()
net = guard_network(Path("net_core.jsonl"))
import importlib
import pkgutil
import kgbuilder
for item in sorted(pkgutil.walk_packages(kgbuilder.__path__, "kgbuilder."), key=lambda item: item.name):
    importlib.import_module(item.name)
import kg_gen
import dspy
import litellm
from sentence_transformers import SentenceTransformer
from kgbuilder.runtime.gateway import Gateway
gateway = Gateway("http://127.0.0.1:9/v1", Path("llm_calls.jsonl"), None, "readonly")
try:
    url = gateway.start()
    SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    kg_gen.KGGen(model="lm_studio/qwen3.6-35b-a3b", api_base=url,
                 api_key="lm-studio", disable_cache=True)
    assert blocked_count(net) == 0
finally:
    gateway.stop()
"""
        result = subprocess.run([str(PY_CORE), "-c", code], cwd=self.tmp, env=self.child_env(),
                                capture_output=True, text=True, encoding="utf-8", timeout=180)
        (self.tmp / "core_stdout.txt").write_text(result.stdout, encoding="utf-8")
        (self.tmp / "core_stderr.txt").write_text(result.stderr, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        net = self.tmp / "net_core.jsonl"
        self.assertTrue(net.is_file())
        self.assertEqual(blocked_count(net), 0, net.read_text(encoding="utf-8"))
        self.worker_selftest()

    def build_and_check(self, name, config, canon_off, env=None, webnlg=False):
        out = PROJECT_ROOT / "runs/_test" / name
        args = ["build", "--config", config, "--ablation", "A4", "--mock",
                "--out", str(out), "--overwrite"]
        if canon_off:
            args += ["--set", "flags.canon=false"]
        result = run_kgb(args, timeout=900, test_id=name, env_extra=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if webnlg:
            result = run_kgb(["eval", "webnlg", "--run", str(out)], timeout=1800, env_extra=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        logs = [out / "net.jsonl"]
        if not canon_off:
            logs.append(out / "net_edc.jsonl")
        if webnlg:
            logs.append(out / "eval/net_eval.jsonl")
        for path in logs:
            self.assertTrue(path.is_file(), path)
            self.assertEqual(blocked_count(path), 0, path.read_text(encoding="utf-8"))

    def test_pipeline_run_offline(self):
        self.build_and_check("network_offline", "configs/experiments/showcase.yaml", True)
        if LIVE_FIXTURE.is_file():
            self.build_and_check("network_showcase_full", "configs/experiments/showcase.yaml", False)
            self.build_and_check("network_webnlg_full", "configs/experiments/webnlg10.yaml", False, webnlg=True)

    def test_cli_external_hosts(self):
        for override, key in [("llm.base_url=http://api.openai.com/v1", "llm.base_url"),
                              ("neo4j.uri=bolt://192.168.1.5:7687", "neo4j.uri")]:
            result = run_kgb(["build", "--config", "configs/experiments/showcase.yaml", "--mock", "--set", override])
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(key, result.stderr)

    def test_worker_health_logs(self):
        ok = self.tmp / "core.jsonl"
        write_jsonl(ok, [])
        for name in ["net_edc.jsonl", "net_eval.jsonl"]:
            bad = self.tmp / name
            write_jsonl(bad, [{"kind": "connect", "target": "external.invalid:443", "allowed": False}])
            with self.assertRaises(KgbError) as cm:
                check_health(None, [ok, bad])
            self.assertEqual(cm.exception.code, 4)
            self.assertIn(name, str(cm.exception))

    def test_no_proxy_env(self):
        code = """
from pathlib import Path
from kgbuilder.runtime.onprem import load_env, guard_network
load_env()
guard_network(Path("net.jsonl"))
import json
import urllib.request
print(json.dumps(urllib.request.getproxies()))
"""
        env = self.child_env({"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"})
        result = subprocess.run([str(PY_CORE), "-c", code], cwd=self.tmp, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        proxies = json.loads(result.stdout)
        self.assertNotIn("http", proxies)
        self.assertNotIn("https", proxies)
        self.assertEqual(proxies, {"no": "*"})

    def test_no_files_outside_project(self):
        home = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/fake_home")
        env = {"USERPROFILE": str(home / "profile"), "HOME": str(home / "profile"),
               "APPDATA": str(home / "appdata"), "LOCALAPPDATA": str(home / "localappdata")}
        for directory in env.values():
            Path(directory).mkdir(parents=True, exist_ok=True)
        self.build_and_check("home", "configs/experiments/showcase.yaml", True, env)
        self.worker_selftest(env)
        self.assertEqual([str(p.relative_to(home)) for p in home.rglob("*") if p.is_file()], [])
        if LIVE_FIXTURE.is_file():
            self.build_and_check("home_showcase_full", "configs/experiments/showcase.yaml", False, env)
            self.build_and_check("home_webnlg_full", "configs/experiments/webnlg10.yaml", False, env, webnlg=True)
            self.assertEqual([str(p.relative_to(home)) for p in home.rglob("*") if p.is_file()], [])


if __name__ == "__main__": unittest.main()
