"""Loopback LLM gateway with Qwen no-thinking rendering and JSONL replay."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kgbuilder.runtime.onprem import require_loopback_url

STOP = ["<|im_end|>", "<|endoftext|>", "<|im_start|>"]
MIN_TOKENS = 4
PLAN_LEAF = ("judge", "qa.", "induce.")
DEFAULT_PROFILE = "lmstudio"
DEFAULT_MODE = "completions_chatml"
PASS_THROUGH = ("temperature", "top_p", "top_k", "seed", "presence_penalty", "frequency_penalty", "repeat_penalty", "response_format")


def _text(content) -> str:
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def render(messages: list) -> str:
    """Render ChatML ending with Qwen's explicit empty thinking block."""
    parts = [f"<|im_start|>{m['role']}\n{_text(m.get('content'))}<|im_end|>\n" for m in messages]
    return "".join(parts) + "<|im_start|>assistant\n<think>\n\n</think>\n\n"


def request_key(req: dict) -> str:
    """Hash the complete completions request using the specified encoding."""
    return hashlib.sha256(json.dumps(req, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def cache_key(req: dict, profile: str = DEFAULT_PROFILE) -> str:
    """Add profile isolation while preserving LM Studio keys."""
    return request_key(req) if profile == DEFAULT_PROFILE else request_key({**req, "kgb_profile": profile})


def row_key(row: dict) -> str | None:
    """Reconstruct a key from a valid recorded call with non-null content."""
    if not isinstance(row, dict) or row.get("content") is None:
        return None
    try:
        params, messages = row["params"], row["messages"]
        if not isinstance(params, dict) or not isinstance(messages, list) or "model" not in params:
            return None
        mode = row.get("request_mode", DEFAULT_MODE)
        req = {**params, "prompt": render(messages)} if mode == DEFAULT_MODE else {**params, "messages": messages}
        return cache_key(req, row.get("profile", DEFAULT_PROFILE))
    except (TypeError, KeyError):
        return None


def load_replay(paths: list) -> tuple[dict, int]:
    """Index JSONL call rows in source order, keeping the first occurrence."""
    index, skipped = {}, 0
    for value in paths:
        path = Path(value)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            key = row_key(row)
            if key is None:
                skipped += 1
            else:
                index.setdefault(key, row)
    return index, skipped


def replay_gaps(paths: list) -> dict:
    """Inspect failed requests and keys that recorded replay cannot serve."""
    count, skipped, failed = 0, 0, 0
    needed, replayable, stages = set(), set(), {}
    for value in paths:
        path = Path(value)
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            count += 1
            key = row_key(row)
            if key is not None:
                replayable.add(key)
            if not isinstance(row, dict):
                continue
            key = row.get("key")
            if isinstance(key, str):
                stages.setdefault(key, row.get("stage"))
                if not row.get("miss"):
                    needed.add(key)
                    failed += int(row.get("content") is None)
    return {"rows": count, "skipped": skipped, "failed_rows": failed,
            "unreplayable": [{"key": key[:12], "stage": stages[key]}
                             for key in sorted(needed - replayable)]}


class Gateway:
    """Serve a chat-compatible loopback endpoint with optional replay."""

    def __init__(self, upstream_base: str, log_path: Path, cache_path: Path | None, cache_mode: str, replay_paths: list = (), timeout_s: int = 600, max_concurrency: int = 2,
                 profile: str = DEFAULT_PROFILE, request_mode: str = DEFAULT_MODE, api_key_env: str = "LMSTUDIO_API_KEY"):
        require_loopback_url(upstream_base, "llm.base_url", ("http", "https"))
        if cache_mode not in {"off", "readwrite", "readonly", "plan"}:
            raise ValueError(f"invalid cache mode: {cache_mode}")
        self.upstream = upstream_base.rstrip("/")
        self.profile, self.request_mode, self.api_key_env = profile, request_mode, api_key_env
        self.log_path, self.cache_path, self.cache_mode = Path(log_path), Path(cache_path) if cache_path else None, cache_mode
        paths = list(replay_paths)
        if cache_mode != "off" and self.cache_path is not None and self.cache_path.exists(): paths.append(self.cache_path)
        self._index, self._skipped = load_replay(paths)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._lock = threading.RLock(); self._semaphore = threading.BoundedSemaphore(max_concurrency)
        self._server = None; self._thread = None; self._stage = ""; self._failures = 0; self.timeout_s = timeout_s; self.fatal = None
        self.stats = dict(calls=0, cache_hits=0, cache_misses=0, prompt_tokens=0, completion_tokens=0, seconds=0.0, finish_length=0, upstream_errors=0)
        self.set_log(self.log_path)

    def set_stage(self, name: str) -> None:
        """Set the stage included in subsequent call records."""
        with self._lock:
            self._stage = name

    def set_log(self, path: Path) -> None:
        """Switch per-run logs without resetting the process-wide state."""
        with self._lock:
            self.log_path = Path(path)
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_path.touch(exist_ok=True)

    def _record(self, row: dict, cache: bool = False) -> None:
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with self._lock:
            with self.log_path.open("a", encoding="utf-8", newline="\n") as fh: fh.write(line)
            if cache:
                self._index.setdefault(row["key"], row)
                if self.cache_path is not None:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.cache_path.open("a", encoding="utf-8", newline="\n") as fh:
                        fh.write(line)
            self.stats["calls"] += 1; self.stats["cache_hits"] += int(row.get("cache_hit", False)); self.stats["cache_misses"] += int(row.get("miss", False))
            self.stats["prompt_tokens"] += row["usage"].get("prompt_tokens", 0); self.stats["completion_tokens"] += row["usage"].get("completion_tokens", 0)
            self.stats["seconds"] += row["seconds"]; self.stats["finish_length"] += int(row.get("finish_reason") == "length")

    def _failed(self, msg: str) -> None:
        with self._lock:
            self._failures += 1; self.stats["upstream_errors"] += 1
            if self._failures >= 3 and self.fatal is None: self.fatal = "upstream_failed:" + msg

    def _request(self, path: str, method: str, data: bytes | None):
        req = urllib.request.Request(self.upstream + path, data=data, method=method, headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ.get(self.api_key_env, "lm-studio")})
        try:
            with self._semaphore:
                with self._opener.open(req, timeout=self.timeout_s) as res:
                    result = res.status, res.read(), res.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            if exc.code >= 500:
                self._failed(str(exc))
            else:
                with self._lock:
                    self._failures = 0
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self._failed(str(exc))
            raise
        with self._lock:
            self._failures = 0
        return result

    def _chat(self, body: dict):
        asked = body.get("max_tokens") or body.get("max_completion_tokens") or 1024
        stop = body.get("stop"); stop = [stop] if isinstance(stop, str) else list(stop or [])
        req = {"model": body["model"], "prompt": render(body["messages"]), "max_tokens": max(asked, MIN_TOKENS), "stop": STOP + stop}
        if self.request_mode == "chat_nothink":
            req.pop("prompt")
            req.update(messages=body["messages"], chat_template_kwargs={"enable_thinking": False})
        req.update({k: body[k] for k in PASS_THROUGH if k in body}); key = cache_key(req, self.profile)
        row = {"t": round(time.time(), 2), "stage": self._stage, "key": key, "cache_hit": False, "seconds": 0, "usage": {}, "finish_reason": None, "asked_max_tokens": asked, "params": {k: v for k, v in req.items() if k not in {"prompt", "messages"}}, "messages": body["messages"], "content": None}
        if self.profile != DEFAULT_PROFILE or self.request_mode != DEFAULT_MODE: row.update(profile=self.profile, request_mode=self.request_mode)
        with self._lock:
            cached = self._index.get(key) if self.cache_mode != "off" else None
        if cached is not None:
            row.update(cache_hit=True, content=cached["content"], usage=cached.get("usage", {}), finish_reason=cached.get("finish_reason"))
        elif self.cache_mode == "plan" and (row["stage"] == PLAN_LEAF[0] or row["stage"].startswith(PLAN_LEAF[1:])):
            row.update(miss=True, planned=True)
            self._record(row)
            return 200, {"id": "kgb", "object": "chat.completion", "created": int(row["t"]),
                         "model": body["model"], "usage": {}, "choices": [{"index": 0, "finish_reason": "plan",
                         "message": {"role": "assistant", "content": ""}}]}
        elif self.cache_mode in {"readonly", "plan"}:
            row["miss"] = True; self._record(row)
            with self._lock:
                if self.fatal is None:
                    self.fatal = "cache_miss:" + key[:12]
            return 503, {"error": {"message": "kgb cache miss " + key[:12]}}
        else:
            start = time.monotonic()
            try:
                endpoint = "/completions" if self.request_mode == DEFAULT_MODE else "/chat/completions"
                _, payload, _ = self._request(endpoint, "POST", json.dumps(req).encode("utf-8")); out = json.loads(payload); choice = out["choices"][0]
                content = choice.get("text", "") if self.request_mode == DEFAULT_MODE else (choice.get("message", {}).get("content") or "")
                row.update(seconds=round(time.monotonic() - start, 2), usage=out.get("usage", {}), finish_reason=choice.get("finish_reason"), content=content)
            except urllib.error.HTTPError as exc:
                self._record(row); return exc.code, exc.read()
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self._record(row)
                return 502, {"error": {"message": str(exc)}}
            except (ValueError, KeyError, IndexError) as exc:
                self._failed(str(exc)); self._record(row); return 502, {"error": {"message": str(exc)}}
        self._record(row, cache=self.cache_mode == "readwrite" and not row["cache_hit"])
        return 200, {"id": "kgb", "object": "chat.completion", "created": int(row["t"]), "model": body["model"], "usage": row["usage"], "choices": [{"index": 0, "finish_reason": row["finish_reason"], "message": {"role": "assistant", "content": row["content"]}}]}

    def start(self) -> str:
        """Start the gateway and return its loopback URL ending in /v1."""
        if self._server is not None:
            return f"http://127.0.0.1:{self._server.server_address[1]}/v1"
        gateway = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def reply(self, code, payload, content_type="application/json"):
                if not isinstance(payload, bytes): payload = json.dumps(payload).encode("utf-8")
                self.send_response(code); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
            def forward(self, method, data=None):
                if gateway.cache_mode == "plan":
                    return self.reply(503, {"error": {"message": "kgb plan mode: no upstream request"}})
                path = self.path[3:] if self.path.startswith("/v1") else self.path
                try: code, payload, content_type = gateway._request(path, method, data)
                except urllib.error.HTTPError as exc: return self.reply(exc.code, exc.read())
                except (urllib.error.URLError, TimeoutError, OSError) as exc: return self.reply(502, {"error": {"message": str(exc)}})
                self.reply(code, payload, content_type)
            def do_GET(self): self.forward("GET")
            def do_POST(self):
                data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if not self.path.rstrip("/").endswith("/chat/completions"): return self.forward("POST", data)
                try: code, payload = gateway._chat(json.loads(data))
                except (ValueError, KeyError, TypeError) as exc: return self.reply(400, {"error": {"message": str(exc)}})
                self.reply(code, payload)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler); self._thread = threading.Thread(target=self._server.serve_forever, daemon=True); self._thread.start()
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def stop(self) -> None:
        """Stop the gateway server."""
        if self._server is not None: self._server.shutdown(); self._server.server_close(); self._thread.join(); self._server = None


def start(upstream_base: str, log_path: Path) -> str:
    """Compatibility helper for upstream minitests."""
    return Gateway(upstream_base, log_path, None, "off").start()


def summarize(log_path: Path) -> dict:
    """Summarize calls and usage; readonly misses contribute no tokens or time."""
    rows = [json.loads(x) for x in Path(log_path).read_text(encoding="utf-8").splitlines() if x.strip()] if Path(log_path).exists() else []
    normal = [r for r in rows if not r.get("miss")]
    return {"llm_calls": len(rows), "cache_hits": sum(bool(r.get("cache_hit")) for r in rows), "cache_misses": sum(bool(r.get("miss")) for r in rows), "prompt_tokens": sum(r.get("usage", {}).get("prompt_tokens", 0) for r in normal), "completion_tokens": sum(r.get("usage", {}).get("completion_tokens", 0) for r in normal), "llm_seconds": round(sum(r.get("seconds", 0) for r in normal), 1), "finish_length": sum(r.get("finish_reason") == "length" for r in normal)}


def planned_calls(paths: list) -> dict:
    """Count distinct planned keys without mistaking them for replayable calls."""
    rows = [json.loads(line) for path in paths if Path(path).is_file()
            for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    planned = [r for r in rows if r.get("planned")]
    stages = {}
    for row in planned:
        stages.setdefault(row["stage"], set()).add(row["key"])
    return {"rows": len(rows), "planned_rows": len(planned), "planned_keys": len({r["key"] for r in planned}),
            "by_stage": {stage: len(keys) for stage, keys in sorted(stages.items())},
            "replayed": sum(bool(r.get("cache_hit")) for r in rows)}
