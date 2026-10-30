"""One OpenAI-compatible model client for hosted (OpenRouter) and local (llama.cpp, vLLM) endpoints.

Every call records the endpoint, model, tokens, seconds and cost (B-D02), is cached by its full request
(B-C04), can be constrained to a JSON schema (B-C02), and is refused when private data would go to a
hosted endpoint (FR-28).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
ENDPOINTS = ROOT / "configs/graphrag/endpoints.json"
CACHE = ROOT / "data/interim/graphrag/cache"


class PrivateDataError(RuntimeError):
    """Raised when a non-public document would be sent to a hosted endpoint."""


@dataclass(frozen=True)
class Endpoint:
    name: str
    base_url: str
    hosted: bool
    api_key_env: str | None = None
    # US$ per million tokens, used when the endpoint does not report cost itself.
    price_in: float = 0.0
    price_out: float = 0.0


@dataclass
class Call:
    endpoint: str
    model: str
    content: str
    parsed: Any
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    cost_usd: float
    cached: bool


@dataclass
class Ledger:
    """Running totals for one run, reported next to quality (B-D02)."""
    calls: int = 0
    cached_calls: int = 0
    invalid_json: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    models: set[str] = field(default_factory=set)

    def add(self, call: Call, schema: dict | None) -> None:
        self.calls += 1
        self.cached_calls += call.cached
        self.invalid_json += schema is not None and call.parsed is None
        self.prompt_tokens += call.prompt_tokens
        self.completion_tokens += call.completion_tokens
        self.seconds += call.seconds
        self.cost_usd += call.cost_usd
        self.models.add(f"{call.endpoint}:{call.model}")

    def summary(self) -> dict[str, Any]:
        out = asdict(self)
        out["models"] = sorted(self.models)
        out["seconds"] = round(self.seconds, 1)
        out["cost_usd"] = round(self.cost_usd, 6)
        return out


def load_endpoints(path: Path = ENDPOINTS) -> dict[str, Endpoint]:
    return {e["name"]: Endpoint(**e) for e in json.loads(path.read_text(encoding="utf-8"))}


class ModelClient:
    def __init__(self, endpoint: Endpoint, model: str, cache_dir: Path | None = CACHE, timeout: float = 900):
        self.endpoint, self.model, self.cache_dir, self.timeout = endpoint, model, cache_dir, timeout
        self.ledger = Ledger()

    def chat(self, messages: list[dict[str, str]], schema: dict | None = None, max_tokens: int = 800,
             temperature: float = 0.0, data_class: str = "public") -> Call:
        if self.endpoint.hosted and data_class != "public":
            raise PrivateDataError(f"{data_class} data may not go to hosted endpoint {self.endpoint.name}")
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": temperature,
                                "max_tokens": max_tokens}
        if schema is not None:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "output", "strict": True, "schema": schema}}
        if self.endpoint.name == "openrouter":
            body["usage"] = {"include": True}
        key = hashlib.sha256(json.dumps([self.endpoint.base_url, body], sort_keys=True).encode()).hexdigest()
        call = self._cached(key) or self._post(body, key)
        call.parsed = _parse(call.content) if schema is not None else None
        self.ledger.add(call, schema)
        return call

    def embed(self, texts: list[str], data_class: str = "public") -> list[list[float]]:
        """Embeddings from the endpoint's /embeddings route; counted in the ledger like chat calls."""
        if self.endpoint.hosted and data_class != "public":
            raise PrivateDataError(f"{data_class} data may not go to hosted endpoint {self.endpoint.name}")
        started = time.perf_counter()
        response = httpx.post(f"{self.endpoint.base_url}/embeddings", json={"model": self.model, "input": texts},
                              headers=self._headers(), timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        prompt = (data.get("usage") or {}).get("prompt_tokens", 0)
        call = Call(self.endpoint.name, self.model, "", None, prompt, 0, round(time.perf_counter() - started, 3),
                    prompt * self.endpoint.price_in / 1e6, False)
        self.ledger.add(call, None)
        return [row["embedding"] for row in sorted(data["data"], key=lambda row: row["index"])]

    def _headers(self) -> dict[str, str]:
        if not self.endpoint.api_key_env:
            return {}
        token = os.environ.get(self.endpoint.api_key_env)
        if not token:
            raise RuntimeError(f"set {self.endpoint.api_key_env} to use endpoint {self.endpoint.name}")
        return {"Authorization": f"Bearer {token}"}

    def _cached(self, key: str) -> Call | None:
        path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if not path or not path.exists():
            return None
        call = Call(**json.loads(path.read_text(encoding="utf-8")))
        # A cache hit costs nothing now; the original cost stays in the cache file.
        call.cached, call.seconds, call.cost_usd = True, 0.0, 0.0
        return call

    def _post(self, body: dict[str, Any], key: str) -> Call:
        started = time.perf_counter()
        response = httpx.post(f"{self.endpoint.base_url}/chat/completions", json=body, headers=self._headers(),
                              timeout=self.timeout)
        response.raise_for_status()
        seconds = time.perf_counter() - started
        data = response.json()
        usage = data.get("usage") or {}
        prompt, completion = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        cost = usage.get("cost")
        if cost is None:
            cost = (prompt * self.endpoint.price_in + completion * self.endpoint.price_out) / 1e6
        call = Call(self.endpoint.name, data.get("model", self.model), data["choices"][0]["message"]["content"] or "",
                    None, prompt, completion, round(seconds, 3), float(cost), False)
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{key}.json").write_text(json.dumps(asdict(call)), encoding="utf-8")
        return call


def _parse(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None
