"""One OpenAI-compatible model client for hosted (OpenRouter) and local (llama.cpp, vLLM) endpoints.

Every call records the endpoint, model, tokens, seconds and cost (B-D02), is cached by its full request
(B-C04), can be constrained to a JSON schema (B-C02), and is refused when private data would go to a
hosted endpoint (FR-28).

A model profile (`configs/graphrag/models/<name>.json`) names one model on one endpoint with what it needs there:
extra request fields (such as how thinking is turned off), its context and its prices. Code takes a profile where it
takes an endpoint name, and `GRAPHRAG_PROFILE` puts one profile on the roles it lists (graphrag/README.md, "Trying a model"). A profile's calls are cached apart from every other profile's.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
# A deployment points at its own model servers by naming other files, with no change to the repository.
ENDPOINTS = Path(os.environ.get("GRAPHRAG_ENDPOINTS") or ROOT / "configs/graphrag/endpoints.json")
ROLES = Path(os.environ.get("GRAPHRAG_ROLES") or ROOT / "configs/graphrag/roles.json")
PROFILES = ROOT / "configs/graphrag/models"
CACHE = ROOT / "data/interim/graphrag/cache"
MODEL_ROLES = ("frame", "answer", "extract")  # the roles a profile can serve; embeddings stay on their own endpoint


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
    # Fields added to every chat request, such as OpenRouter's `reasoning`; they are part of the cache key.
    request: dict | None = None
    # Set for a profile: its name and model file, so two profiles never share cached answers.
    cache_tag: str = ""


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
    provider: str = ""  # who served it, when a router such as OpenRouter says
    reasoning: str = ""  # a reasoning block the server returned beside the content; empty when thinking is off
    reasoning_tokens: int = 0
    # On a cache hit: the seconds and cost the call took when it was made, so a resumed run can report them.
    cached_seconds: float = 0.0
    cached_cost_usd: float = 0.0


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
    # What the cached calls took when they were made: with `seconds` and `cost_usd`, a resumed run's whole cost.
    cached_seconds: float = 0.0
    cached_cost_usd: float = 0.0
    models: set[str] = field(default_factory=set)
    providers: set[str] = field(default_factory=set)

    def add(self, call: Call, schema: dict | None) -> None:
        self.calls += 1
        self.cached_calls += call.cached
        self.invalid_json += schema is not None and call.parsed is None
        self.prompt_tokens += call.prompt_tokens
        self.completion_tokens += call.completion_tokens
        self.seconds += call.seconds
        self.cost_usd += call.cost_usd
        self.cached_seconds += call.cached_seconds
        self.cached_cost_usd += call.cached_cost_usd
        self.models.add(f"{call.endpoint}:{call.model}")
        if call.provider:
            self.providers.add(call.provider)

    def summary(self) -> dict[str, Any]:
        out = asdict(self)
        out["models"], out["providers"] = sorted(self.models), sorted(self.providers)
        out["seconds"], out["cached_seconds"] = round(self.seconds, 1), round(self.cached_seconds, 1)
        out["cost_usd"], out["cached_cost_usd"] = round(self.cost_usd, 6), round(self.cached_cost_usd, 6)
        return out


# ---- endpoints, profiles and roles ------------------------------------------------------------------------------

_REGISTERED: dict[str, Endpoint] = {}


class Endpoints(dict):
    """The endpoints file, where a name that is not in it is looked up as a model profile (by name or path), so
    every command that takes an endpoint name also takes a profile."""

    def __missing__(self, name: str) -> Endpoint:
        if name in _REGISTERED:
            return _REGISTERED[name]
        try:
            return profile_endpoint(load_profile(name))
        except FileNotFoundError:
            raise KeyError(name) from None

    def get(self, name: str, default: Any = None) -> Any:
        try:
            return self[name]
        except KeyError:
            return default


def load_endpoints(path: Path = ENDPOINTS) -> dict[str, Endpoint]:
    return Endpoints({e["name"]: Endpoint(**e) for e in json.loads(path.read_text(encoding="utf-8"))})


def register(spec: str, endpoint: Endpoint) -> None:
    """Makes `endpoint` the one a profile spec resolves to in this process, for a run that has learnt more about it
    than its file says (`graphrag.bench run` adds the model file the server reports to its cache tag)."""
    _REGISTERED[spec] = endpoint


def _profile_path(spec: str) -> Path | None:
    path = Path(spec)
    if path.suffix == ".json":
        return path if path.is_absolute() or path.is_file() else ROOT / path
    named = PROFILES / f"{spec}.json"
    return named if named.is_file() else None


def load_profile(spec: str) -> dict[str, Any]:
    """A model profile from a profile name (`configs/graphrag/models/<name>.json`), a path to a profile file, or
    `endpoint:model` for a model on an endpoint of the endpoints file. The result always has `spec` (what was
    given), `name`, `model`, `hosted` and `roles`."""
    path = _profile_path(spec)
    if path is not None:
        if not path.is_file():
            raise FileNotFoundError(f"no model profile at {path}")
        profile, name = json.loads(path.read_text(encoding="utf-8")), path.stem
    elif ":" in spec:
        endpoint, model = spec.split(":", 1)
        # Comparable with the recorded runs of the same endpoint and model (graphrag.bench compare).
        profile, name = {"endpoint": endpoint, "model": model, "compare_as": spec, "inline": True}, spec
    else:
        known = ", ".join(sorted(p.stem for p in PROFILES.glob("*.json")))
        raise FileNotFoundError(f"no model profile {spec!r}: give one of {known}, a profile file, or endpoint:model")
    if "model" not in profile or not ("endpoint" in profile or "base_url" in profile):
        raise ValueError(f"model profile {spec!r} needs `model` and either `endpoint` or `base_url`")
    # A profile may make an endpoint of the file stricter (hosted), never less strict.
    hosted = (_file_endpoint(profile["endpoint"]).hosted or profile.get("hosted", False)) if "endpoint" in profile \
        else profile.get("hosted", True)
    roles = profile.get("roles", list(MODEL_ROLES))
    if unknown := set(roles) - set(MODEL_ROLES):
        raise ValueError(f"model profile {spec!r} names roles it cannot serve: {sorted(unknown)}")
    return {**profile, "spec": spec, "name": name, "hosted": hosted, "roles": roles}


def _file_endpoint(name: str) -> Endpoint:
    endpoints = {e["name"]: Endpoint(**e) for e in json.loads(ENDPOINTS.read_text(encoding="utf-8"))}
    if name not in endpoints:
        raise FileNotFoundError(f"no endpoint {name!r} in {ENDPOINTS}")
    return endpoints[name]


def _loopback(url: str) -> bool:
    host = urlparse(url).hostname or ""
    try:
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def profile_endpoint(profile: dict[str, Any], served: str | None = None) -> Endpoint:
    """The endpoint a profile's calls go to. An endpoint named from the endpoints file keeps its address, key and
    hosted flag; a profile's own `base_url` is hosted unless it says otherwise, and only a server on this machine
    (127.0.0.1, usually through an SSH tunnel) may say so: any other machine is someone else's (D-68).
    `served` is what the server reports it runs (model file and build), when it reports it."""
    if "endpoint" in profile:
        base = _file_endpoint(profile["endpoint"])
    else:
        if not profile["hosted"] and not _loopback(profile["base_url"]):
            raise ValueError(f"profile {profile['name']}: {profile['base_url']} is not on this machine, so it counts "
                             f"as hosted (D-68); reach it through an SSH tunnel to 127.0.0.1 or set hosted to true")
        base = Endpoint(profile["name"], profile["base_url"].rstrip("/"), True, profile.get("api_key_env"))
    if profile.get("inline") and not served:
        return base  # endpoint:model is the endpoint of the file as it is, cached as it always was
    # An inline profile keeps the endpoint's name, so its ledger reads endpoint:model like the recorded runs.
    return Endpoint(base.name if profile.get("inline") else profile["name"], base.base_url, profile["hosted"],
                    base.api_key_env, float(profile.get("price_in", base.price_in)),
                    float(profile.get("price_out", base.price_out)), profile.get("request") or base.request,
                    f"{profile['name']}|{served or profile.get('file', '')}")


def resolve(spec: str) -> tuple[Endpoint, str]:
    """What `ModelClient` needs for a profile name, a profile file or `endpoint:model`."""
    profile = load_profile(spec)
    return _REGISTERED.get(spec) or profile_endpoint(profile), profile["model"]


def load_roles(path: Path = ROLES) -> dict[str, dict[str, str]]:
    """Which endpoint and model serve each role (specification §4.1, D-62): frame, answer, extract, embed.

    A role may name a profile instead (`{"profile": "qwen3-8b.openrouter"}`), and `GRAPHRAG_PROFILE` puts one profile
    on every role it lists. Either way the role reads `{"endpoint": <profile>, "model": <its model>, "profile": ...}`,
    and `load_endpoints()[<profile>]` is the profile's endpoint."""
    roles = json.loads(path.read_text(encoding="utf-8"))
    if os.environ.get("GRAPHRAG_PROFILE"):
        chosen = load_profile(os.environ["GRAPHRAG_PROFILE"])
        roles.update({role: {"profile": chosen["spec"]} for role in chosen["roles"]})
    out = {}
    for role, chosen in roles.items():
        if "profile" in chosen:
            profile = load_profile(chosen["profile"])
            chosen = {"endpoint": profile["spec"], "model": profile["model"], "profile": profile["name"]}
        out[role] = chosen
    return out


# ---- the client --------------------------------------------------------------------------------------------------

_DEFAULT_CACHE = object()


class ModelClient:
    def __init__(self, endpoint: Endpoint, model: str, cache_dir: Path | None = _DEFAULT_CACHE,  # type: ignore[assignment]
                 timeout: float = 900):
        self.endpoint, self.model, self.timeout = endpoint, model, timeout
        self.cache_dir = CACHE if cache_dir is _DEFAULT_CACHE else cache_dir
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
        if self.endpoint.name == "openrouter" or "openrouter.ai" in self.endpoint.base_url:
            body["usage"] = {"include": True}
        body.update(self.endpoint.request or {})
        # The address, the whole request and the profile: a different model, server setting or profile never
        # reads another's answer. Without a profile the key is what it always was, so old caches stay valid.
        keyed = [self.endpoint.base_url, body] + ([self.endpoint.cache_tag] if self.endpoint.cache_tag else [])
        key = hashlib.sha256(json.dumps(keyed, sort_keys=True).encode()).hexdigest()
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
        # A cache hit costs nothing now; what it cost when it was made is kept beside it.
        call.cached_seconds, call.cached_cost_usd = call.seconds, call.cost_usd
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
        message = data["choices"][0]["message"]
        call = Call(self.endpoint.name, data.get("model", self.model), message.get("content") or "",
                    None, prompt, completion, round(seconds, 3), float(cost), False,
                    provider=str(data.get("provider") or ""),
                    reasoning=str(message.get("reasoning_content") or message.get("reasoning") or ""),
                    reasoning_tokens=int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0))
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{key}.json").write_text(json.dumps(asdict(call)), encoding="utf-8")
        return call


def client_for(role: str, roles: dict[str, dict[str, str]] | None = None, **kwargs: Any) -> ModelClient:
    """The client for a role. Code names the role; the roles file names the model, so a model is swapped there."""
    chosen = (roles or load_roles())[role]
    return ModelClient(load_endpoints()[chosen["endpoint"]], chosen["model"], **kwargs)


def _parse(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None
