"""A stand-in for llama.cpp, ONLY for testing the deployment's wiring without a GPU. It is not a model.

    python scripts/stub_model_server.py --host 127.0.0.1 --port 8080

It speaks the three OpenAI-compatible routes `graphrag/client.py` uses: `GET /v1/models`, `POST /v1/chat/completions`
and `POST /v1/embeddings`. Every reply is deterministic and labelled:

- A chat request with a JSON-schema `response_format` gets JSON that is valid under that schema, built from the
  schema and the request: an enum takes its first value, a number its minimum or 0, an array one item. A `chunk`
  field names the first passage of the prompt and a `quote` field copies its first words, so citations point at
  real passages; plan fields (`well`, `code`, dates, `unit`) stay empty; every other text starts with "[stub model]".
- A chat request without a schema gets one sentence that starts with "[stub model]".
- An embedding is a small vector made from a hash of the text: equal texts give equal vectors, nothing more.

So a question asked through the backend completes and shows "[stub model]" in its answer, which proves the proxy,
backend, engine and model client are connected; it says nothing about answer quality. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

LABEL = "[stub model]"
MODELS = ("qwen3-8b", "qwen3-4b", "qwen3-embedding-0.6b")
DIMENSIONS = 16
# Fields a model leaves empty unless the question gives them: the query plan's filters and units.
EMPTY_FIELDS = {"well", "code", "npt_code", "date_from", "date_to", "unit"}
# A passage in an answer prompt: "[c0013] (page 7) text..." (graphrag.baseline.answer_one).
PASSAGE = re.compile(r"^\[([^\]\n]+)\] \(page [^)\n]*\) (.+)$", re.MULTILINE)


def first_passage(messages: list[dict]) -> tuple[str, str]:
    """The label and first words of the first passage in the prompt, or empty strings when there is none."""
    for message in messages:
        found = PASSAGE.search(str(message.get("content") or ""))
        if found:
            return found.group(1), " ".join(found.group(2).split()[:8])
    return "", ""


def instance(schema: dict, messages: list[dict], name: str = "") -> Any:
    """A value valid under `schema` (the subset of JSON Schema the engine sends), the same for the same request."""
    for key in ("anyOf", "oneOf"):
        if schema.get(key):
            return instance(schema[key][0], messages, name)
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    kind = schema.get("type", "object")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "null")
    if kind == "object":
        return {key: instance(sub, messages, key) for key, sub in (schema.get("properties") or {}).items()}
    if kind == "array":
        count = 0 if schema.get("maxItems") == 0 else max(1, schema.get("minItems", 0))
        return [instance(schema.get("items") or {"type": "string"}, messages, name) for _ in range(count)]
    if kind in ("number", "integer"):
        low = schema.get("minimum", schema.get("exclusiveMinimum", 0))
        return int(low) if kind == "integer" else low
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    label, words = first_passage(messages)
    text = {"chunk": label, "quote": words}.get(name)
    if text is None:
        text = "" if name in EMPTY_FIELDS else f"{LABEL} a stand-in reply, not a model's answer"
    if len(text) < schema.get("minLength", 0):
        text = text.ljust(schema["minLength"], ".")
    return text[:schema["maxLength"]] if "maxLength" in schema else text


def tokens(text: str) -> int:
    return len(text.split())


def chat_response(body: dict) -> dict:
    messages = body.get("messages") or []
    response_format = body.get("response_format") or {}
    schema = (response_format.get("json_schema") or {}).get("schema") if response_format.get("type") == "json_schema" else None
    if schema is not None:
        content = json.dumps(instance(schema, messages))
    elif response_format.get("type") == "json_object":
        content = json.dumps({"text": f"{LABEL} a stand-in reply, not a model's answer"})
    else:
        content = f"{LABEL} A stand-in reply for testing the wiring; no model wrote it."
    prompt = sum(tokens(str(m.get("content") or "")) for m in messages)
    return {"id": "stub-" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12],
            "object": "chat.completion", "created": 0, "model": body.get("model", MODELS[0]),
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": tokens(content),
                      "total_tokens": prompt + tokens(content)}}


def vector(text: str) -> list[float]:
    """A unit vector from the text's hash: deterministic and cheap, with no meaning."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [digest[i] - 127.5 for i in range(DIMENSIONS)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [round(x / norm, 6) for x in raw]


def embedding_response(body: dict) -> dict:
    texts = body.get("input")
    texts = [texts] if isinstance(texts, str) else list(texts or [])
    return {"object": "list", "model": body.get("model", MODELS[-1]),
            "data": [{"object": "embedding", "index": i, "embedding": vector(str(t))} for i, t in enumerate(texts)],
            "usage": {"prompt_tokens": sum(tokens(str(t)) for t in texts),
                      "total_tokens": sum(tokens(str(t)) for t in texts)}}


def models_response() -> dict:
    return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "stub"} for m in MODELS]}


class Handler(BaseHTTPRequestHandler):
    server_version = "stub-model/1"

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 (http.server's naming)
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("/v1/models", "/models"):
            self._send(200, models_response())
        elif path in ("/health", "/v1/health"):
            self._send(200, {"status": "ok", "stub": True})
        else:
            self._send(404, {"error": {"message": f"no route {path}"}})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": {"message": "the body is not JSON"}})
            return
        if path in ("/v1/chat/completions", "/chat/completions"):
            self._send(200, chat_response(body))
        elif path in ("/v1/embeddings", "/embeddings"):
            self._send(200, embedding_response(body))
        else:
            self._send(404, {"error": {"message": f"no route {path}"}})


class QuietHandler(Handler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


def make_server(host: str = "127.0.0.1", port: int = 8080, quiet: bool = False) -> ThreadingHTTPServer:
    """The server, not yet serving. `quiet` drops the one log line per request (for tests)."""
    return ThreadingHTTPServer((host, port), QuietHandler if quiet else Handler)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    server = make_server(args.host, args.port)
    print(f"stub model server (not a model) on http://{args.host}:{args.port}/v1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
