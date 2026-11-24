"""The model socket (D-62, D-68): check a model, measure it with the whole suite, compare runs.

    python -m graphrag.bench check qwen3-8b.local
    python -m graphrag.bench run qwen3-8b.local --suite quick
    python -m graphrag.bench run qwen3-8b.openrouter --suite full --k1 data/interim/k1/ak3-demo-v1 --no-embeddings
    python -m graphrag.bench compare bench_qwen3-8b.local_full bench_qwen3-8b.openrouter_full

A model is a profile name (configs/graphrag/models/), a profile file, or endpoint:model (graphrag.client).

- `check` costs three calls and says in a table whether the model is usable here.
- `run` runs the existing commands (graphrag.baseline, graphrag.events, graphrag.coordinator) one after another, one
  request at a time, so each writes its run file where it always does. Beside them, `<name>.bench.json` records the
  profile, the server's settings, the date, every step and the totals. Run the same command again to resume: finished
  steps are skipped and finished questions come from the request cache, which a profile shares with no other.
- `compare` puts runs side by side, one table per profile: runs of different profiles are never lined up.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from typing import Any

import httpx

from . import baseline, coordinator, events, reasoning
from .client import ModelClient, load_profile, profile_endpoint, register
from .data import AK3, load_chunks, load_questions
from .retrieval import BM25

PROBE = "graphrag/gold/ak3_reasoning_probe_v0.json"
EOW_SETS = ("prototype", "simulated", "heldout")
DAILY_SETS = ("ak3_daily", "ak3_daily_heldout")
EVENT_SETS = ("ak3_events", "ak3_events_heldout")
# The fact runs the adopted end-of-well design reads (E27_design_*, B-D29), and its embedding model.
FACT_RUNS = ("E20_graph_three_qwen3-4b", "E27_tables_three")
FUSION = "perwell:fusion:bm25+dense:qwen3-embedding-0.6b"
CHECK_QUESTION = "What total depth did AK-3 reach?"


def _results() -> Path:
    return baseline.RESULTS  # read at call time, so a test can point every command elsewhere


# ---- the server --------------------------------------------------------------------------------------------------

def server_info(endpoint, timeout: float = 15) -> dict:
    """What the server says about itself: the model IDs of /v1/models and, from llama.cpp, the settings of /props."""
    out: dict[str, Any] = {"reachable": False, "models": None, "props": None, "error": ""}
    try:
        headers = ModelClient(endpoint, "", cache_dir=None)._headers()
    except RuntimeError as error:
        return {**out, "error": str(error)}
    try:
        response = httpx.get(f"{endpoint.base_url}/models", headers=headers, timeout=timeout)
        out["reachable"] = True
        if response.is_success:
            out["models"] = [m.get("id") for m in response.json().get("data", [])]
    except (httpx.HTTPError, ValueError) as error:
        out["error"] = f"{type(error).__name__}: {error}"
    root = endpoint.base_url.removesuffix("/v1")
    if not endpoint.hosted:
        try:
            response = httpx.get(f"{root}/props", headers=headers, timeout=timeout)
            out["reachable"] = True
            data = response.json() if response.is_success else {}
            if "default_generation_settings" in data or "model_path" in data:
                settings = data.get("default_generation_settings") or {}
                out["props"] = {"model_path": data.get("model_path"), "n_ctx": settings.get("n_ctx", data.get("n_ctx")),
                                "total_slots": data.get("total_slots"), "build_info": data.get("build_info"),
                                "chat_template_kwargs": data.get("chat_template_kwargs")}
        except (httpx.HTTPError, ValueError):
            pass
    return out


def served_file(server: dict) -> str:
    """The model file a llama.cpp server runs, by file name only, or "" when it does not say."""
    path = ((server.get("props") or {}).get("model_path") or "")
    return PureWindowsPath(path).name if "\\" in path else PurePosixPath(path).name


def _served(server: dict) -> str:
    """Model file and build, for the cache tag: another model or another llama.cpp build is paid for again."""
    props = server.get("props") or {}
    return "@".join(filter(None, [served_file(server), str(props.get("build_info") or "")]))


# ---- check -------------------------------------------------------------------------------------------------------

class _Recorder:
    """Passes calls to a client and keeps the last, so a check can read what a real prompt got back."""

    def __init__(self, client: ModelClient):
        self.client, self.last = client, None

    def chat(self, *args: Any, **kwargs: Any):
        self.last = self.client.chat(*args, **kwargs)
        return self.last


def _schema_error(content: str, schema: dict) -> str:
    """Empty when `content` is JSON valid under `schema`, else what is wrong, in a few words."""
    import jsonschema
    try:
        jsonschema.validate(json.loads(content), schema)
        return ""
    except json.JSONDecodeError:
        return f"not JSON: {content[:80]!r}"
    except jsonschema.ValidationError as error:
        return f"not valid under the schema: {error.message[:120]}"


def _reasoning_pack() -> dict:
    """Evidence of the size the reasoning lane sends at most (reasoning.EVENT_CHARS of events, three daily and three
    end-of-well passages of PASSAGE_CHARS), made of AK-3's committed chunks: the check needs no daily corpus."""
    texts = [c.text for c in load_chunks([AK3])]
    lines = [line for line in (" ".join(part.split()) for text in texts for part in text.split("\n")) if line]
    items, used = [], 0
    for line in lines:
        if used + len(line) > reasoning.EVENT_CHARS:
            break
        items.append({"id": f"E{len(items) + 1}", "kind": "event", "text": line, "chunk": None})
        used += len(line)
    for n in range(1, reasoning.DAY_PASSAGES + reasoning.EOW_PASSAGES + 1):
        kind = "daily" if n <= reasoning.DAY_PASSAGES else "end_of_well"
        text = reasoning._cut(" ".join(texts[2 * n:2 * n + 2]))  # two chunks cut to one passage's length
        items.append({"id": f"P{n}", "kind": kind, "page": 1, "text": text, "chunk": None})
    problem = {"date_from": "2016-08-21", "start": "06:00", "date_to": "2016-08-21", "end": "18:00", "npt_code": "KICK",
               "hours": 12, "events": 3, "depth_ft": [3000, 3010]}
    return {"problem": problem, "items": items, "chars": sum(len(i["text"]) for i in items)}


def check(spec: str) -> list[dict]:
    """The preflight: one row per check with `ok` True, False, or None when it does not apply or did not run."""
    profile = load_profile(spec)
    endpoint, model = profile_endpoint(profile), profile["model"]
    rows: list[dict] = []

    def row(name: str, ok: bool | None, detail: str, fix: str = "", required: bool = True) -> None:
        rows.append({"check": name, "ok": ok, "detail": detail, "fix": fix if ok is False else "", "required": required})

    server = server_info(endpoint)
    if not server["reachable"]:
        row("endpoint answers", False, server["error"] or endpoint.base_url,
            f"Nothing answered at {endpoint.base_url}: start the model server (graphrag/README.md, \"Running locally\"), "
            f"or set the key the profile names, or correct the address." if not server["error"].startswith("set ")
            else f"{server['error'][0].upper()}{server['error'][1:]}.")
        return rows
    row("endpoint answers", True, f"{endpoint.base_url} ({'hosted' if endpoint.hosted else 'not hosted'})")
    ids = server["models"]
    if ids is None:
        row("model ID exists", None, "the endpoint lists no models", required=False)
    else:
        row("model ID exists", model in ids, model if model in ids else f"{model} not among {', '.join(ids[:8])}",
            f"The endpoint does not serve {model!r}: set `model` in the profile to one it lists (on llama.cpp, the "
            f"server's --alias).")
    props = server["props"]
    if props:
        running, wanted = served_file(server), profile.get("file")
        row("model file", not wanted or running == wanted, f"{running}, build {props.get('build_info') or '?'}",
            f"The server runs {running}, the profile names {wanted}: start llama-server with -m <{wanted}> or use "
            f"another profile.")
        context = profile.get("context")
        row("server context", not context or (props.get("n_ctx") or 0) >= context,
            f"n_ctx {props.get('n_ctx')}, {props.get('total_slots')} slot(s)",
            f"The server's context is {props.get('n_ctx')} tokens, the profile says {context}: start llama-server "
            f"with -c {context} -np 1.")
        if (props.get("total_slots") or 1) > 1:
            row("one slot", None, f"{props['total_slots']} slots: measurements send one request at a time anyway "
                                  f"(B-F19); graphrag/README.md starts the server with -np 1", required=False)
    client = ModelClient(endpoint, model, cache_dir=None, timeout=300)
    calls = []

    def attempt(name: str, send) -> Any:
        try:
            call = send()
            calls.append(call)
            return call
        except httpx.HTTPStatusError as error:
            row(name, False, f"HTTP {error.response.status_code}: {error.response.text[:160]}",
                f"The endpoint refused the {name.split(':')[-1].strip()} request ({error.response.status_code}); read "
                f"its message above: a wrong model ID, a missing key or an unsupported field in the profile's request.")
        except httpx.HTTPError as error:
            row(name, False, f"{type(error).__name__}: {error}", "The call did not complete: check that the server "
                                                                  "is up and not overloaded, then run the check again.")
        return None

    framing = coordinator.frame_system(SimpleNamespace(events=[]))
    call = attempt("JSON schema: framing", lambda: client.chat(
        [{"role": "system", "content": framing}, {"role": "user", "content": CHECK_QUESTION}],
        schema=coordinator.FRAME_SCHEMA, max_tokens=320))
    if call is not None:
        error = _schema_error(call.content, coordinator.FRAME_SCHEMA)
        row("JSON schema: framing", not error, error or "valid frame", _SCHEMA_FIX)
    chunks = load_chunks([AK3])
    questions, gold = load_questions("prototype")
    question = next(q for q in questions if q["kind"] == "answerable")
    hits = [cid for cid, _ in BM25(chunks).search(question["question"], 5)]
    recorder = _Recorder(client)
    if attempt("JSON schema: answer", lambda: baseline.answer_one(question, hits, "", {c.id: c for c in chunks},
                                                                  recorder, gold) and recorder.last) is not None:
        error = _schema_error(recorder.last.content, baseline.ANSWER_SCHEMA)
        row("JSON schema: answer", not error, error or f"valid answer to {question['id']}", _SCHEMA_FIX)
    pack = _reasoning_pack()
    call = attempt("reasoning-size prompt fits", lambda: client.chat(
        reasoning.messages("What are the likely causes of this problem?", pack), schema=reasoning.CAUSE_SCHEMA,
        max_tokens=reasoning.CAUSE_TOKENS))
    if call is not None:
        context = (props or {}).get("n_ctx") or profile.get("context") or 0
        fits = not context or call.prompt_tokens + reasoning.CAUSE_TOKENS <= context
        error = _schema_error(call.content, reasoning.CAUSE_SCHEMA)
        row("reasoning-size prompt fits", fits and not error,
            f"{pack['chars']:,} characters of evidence, {call.prompt_tokens:,} prompt tokens"
            + (f"; reply {error}" if error else ""),
            _SCHEMA_FIX if fits else f"A reasoning prompt and its answer need {call.prompt_tokens + reasoning.CAUSE_TOKENS:,} "
                                     f"tokens, more than the context of {context:,}: raise -c.")
    if calls:
        # A token is three or four characters of this text: twice the tokens its characters allow means hidden thinking.
        thinking = [c for c in calls if c.reasoning or "<think>" in c.content or c.reasoning_tokens
                    or c.completion_tokens > len(c.content) / 2 + 64]
        row("thinking is off", not thinking,
            "no reasoning block; completion tokens " + ", ".join(str(c.completion_tokens) for c in calls) if not thinking
            else f"{len(thinking)} of {len(calls)} replies carry reasoning or far more completion tokens than their text",
            "The model is thinking: on llama.cpp start the server with --jinja --chat-template-kwargs "
            "'{\"enable_thinking\":false}'; on a hosted endpoint set the field that turns it off in the profile's "
            "`request`, or pin a provider that honours it.")
        reported = all(c.prompt_tokens > 0 and c.completion_tokens > 0 for c in calls)
        row("tokens are reported", reported, f"{sum(c.prompt_tokens for c in calls):,} prompt and "
                                            f"{sum(c.completion_tokens for c in calls):,} completion tokens",
            "The endpoint reports no token counts: cost per question cannot be measured on it; use another server "
            "or provider.")
        providers = sorted({c.provider for c in calls if c.provider})
        if providers:
            row("provider", None, ", ".join(providers) + (": pin one with the request's provider.order before a run"
                                                          if len(providers) > 1 else ""), required=False)
        if any(STAND_IN in c.content for c in calls):
            row("stand-in server", None, "the replies come from scripts/stub_model_server.py: this proves the wiring, "
                                         "never quality", required=False)
        answer_call = recorder.last or calls[0]
        row("seconds for one call", None, f"{answer_call.seconds:.2f} s for the answer call; "
                                          f"US${sum(c.cost_usd for c in calls):.5f} for the check", required=False)
    return rows


_SCHEMA_FIX = ("The endpoint does not honour `response_format` with a JSON schema: on llama.cpp use build b12015 or "
               "later; on OpenRouter keep provider.require_parameters true in the profile's request so only providers "
               "that support it are used.")


def print_check(spec: str, rows: list[dict]) -> int:
    print(f"Model check for {spec}\n")
    print(table(["Check", "Result", "Detail"],
                [[r["check"], {True: "ok", False: "FAILED", None: "-"}[r["ok"]], r["detail"]] for r in rows],
                text_columns=3))
    failed = [r for r in rows if r["ok"] is False and r["required"]]
    for r in failed:
        print(f"- {r['fix']}")
    print("\nUsable here." if not failed else f"\n{len(failed)} required check(s) failed.")
    return 1 if failed else 0


# ---- run ---------------------------------------------------------------------------------------------------------

def steps(suite: str, name: str, spec: str, model: str, k1: bool, no_embeddings: bool) -> list[dict]:
    """The suite as the commands it runs, each with the run file it writes. Hand-routed means the lane each set was
    answered from before the coordinator (specification §8.4), with the adopted settings (B-D23, B-D26, B-D29)."""
    model_args = ["--endpoint", spec, "--model", model]

    def step(id_: str, experiment: str, command: str, argv: list[str]) -> dict:
        run = f"{name}_{id_.replace('/', '_')}"
        return {"id": id_, "experiment": experiment, "command": command, "argv": [*argv, "--name", run], "run": run,
                "status": "pending"}

    if suite == "quick":
        return [step("quick/prototype", "setup check (CLAUDE.md)", "baseline",
                     ["answer", "--pool", "ak3", "--retriever", "bm25", "--k", "5", *model_args])]
    out = []
    for name_ in EOW_SETS:
        out.append(step(f"hand/{name_}", "E33 hand-routed", "baseline",
                        ["answer", "--pool", "three", "--retriever", "wells:bm25", "--k", "5", "--questions", name_,
                         "--multi-well-retriever", "perwell:bm25" if no_embeddings else FUSION,
                         "--fact-sheet", *FACT_RUNS, "--validate", "--strict-facts",
                         *([] if no_embeddings else ["--sheet-properties", "3"]), *model_args]))
    for name_ in DAILY_SETS:
        out.append(step(f"hand/{name_}", "E33 hand-routed" + (", E32" if k1 else ""), "baseline",
                        ["answer", "--pool", "k1_daily" if k1 else "ak3_daily", "--retriever", "dates:wells:bm25",
                         "--k", "5", "--questions", name_, *model_args]))
    for name_ in EVENT_SETS:
        out.append(step(f"hand/{name_}", "E33 hand-routed" + (", E32" if k1 else ""), "events",
                        ["answer", "--questions", name_, *model_args, *(["--k1"] if k1 else [])]))
    flags = [*(["--k1"] if k1 else []), *(["--no-embeddings"] if no_embeddings else [])]
    out.append(step("coordinator", "E33", "coordinator",
                    ["answer", "--questions", *EOW_SETS, *DAILY_SETS, *EVENT_SETS, *flags]))
    if k1:
        out.append(step("k1/prototype", "E32", "baseline",
                        ["answer", "--pool", "k1_ak3", "--retriever", "bm25", "--k", "5", *model_args]))
    out.append(step("reasoning", "E34", "coordinator", ["answer", "--questions", PROBE, *flags]))
    return out


@contextmanager
def _environment(**values: str | None):
    saved = {key: os.environ.get(key) for key in values}
    os.environ.update({key: value for key, value in values.items() if value is not None})
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _k1_chunks(path: str | None) -> str | None:
    if not path:
        return None
    chunks = Path(path) / "chunks.jsonl" if Path(path).is_dir() else Path(path)
    if not chunks.is_file():
        raise SystemExit(f"No K1 package at {path}: give the package folder or its chunks.jsonl.")
    return str(chunks.resolve())


def _preflight(suite: str, k1: str | None, no_embeddings: bool) -> None:
    """Stops a full run before its first paid call when the run could not finish."""
    if suite != "full":
        return
    # The inputs the daily, event and reasoning steps read, loaded as they will be: no model call.
    try:
        with _environment(GRAPHRAG_K1_CHUNKS=k1):
            daily = events.inputs(bool(k1))[0]
    except (FileNotFoundError, OSError, KeyError, ValueError) as error:
        daily, cause = [], f" ({type(error).__name__}: {error})"
    else:
        cause = ""
    if not daily:
        raise SystemExit(("The K1 package lacks the daily reports or the non-productive-time report (appendix 23)"
                          if k1 else "The daily-report corpus is not on this machine") + cause +
                         ": pass --k1 with a package built by scripts/build_k1_demo_release.py "
                         "(docs/tracks/B-graphrag/next-runs.md).")
    missing = [name for name in FACT_RUNS if not (_results() / f"{name}.json").is_file()]
    if missing:
        raise SystemExit(f"The fact runs {', '.join(missing)} are missing from {_results()}: git pull.")
    if not no_embeddings:
        from .client import load_endpoints
        embed = load_endpoints()["local-embed"]
        if not server_info(embed)["reachable"]:
            raise SystemExit(f"The embedding server does not answer at {embed.base_url}: start it "
                             f"(graphrag/README.md) or pass --no-embeddings.")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _ledgers(result: dict) -> list[dict]:
    cost = result.get("cost") or {}
    return [cost["frame"], cost["answer"]] if "frame" in cost else [cost]


TOTALS = ("calls", "cached_calls", "invalid_json", "prompt_tokens", "completion_tokens", "seconds", "cost_usd",
          "cached_seconds", "cached_cost_usd")


def totals(manifest: dict) -> dict:
    """Calls, tokens, seconds and cost over the finished steps. `seconds` and `cost_usd` are what this run paid;
    `cached_*` what its cached calls cost when they were made, so their sums are the whole run's cost."""
    out: dict[str, Any] = {key: 0 for key in TOTALS}
    out["questions"], providers = 0, set()
    for step in manifest["steps"]:
        path = _results() / f"{step['run']}.json"
        if step["status"] != "done" or not path.is_file():
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        out["questions"] += result.get("questions", 0)
        for ledger in _ledgers(result):
            for key in TOTALS:
                out[key] += ledger.get(key, 0)
            providers |= set(ledger.get("providers") or [])
    out["seconds"], out["cached_seconds"] = round(out["seconds"], 1), round(out["cached_seconds"], 1)
    out["cost_usd"], out["cached_cost_usd"] = round(out["cost_usd"], 6), round(out["cached_cost_usd"], 6)
    out["providers"] = sorted(providers)
    return out


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)


def run(spec: str, suite: str = "quick", name: str | None = None, k1: str | None = None,
        no_embeddings: bool = False, fresh: bool = False) -> dict:
    """Runs the suite on one model and returns its record (`<name>.bench.json`)."""
    profile = load_profile(spec)
    if not {"frame", "answer"} <= set(profile["roles"]):
        raise SystemExit(f"Profile {profile['name']} serves {', '.join(profile['roles'])}; the suite measures the frame "
                         f"and answer roles. Add them to its `roles` to measure it as an answer model.")
    name = safe_name(name or f"bench_{profile['name']}_{suite}")
    base = profile_endpoint(profile)
    server = server_info(base)
    if not server["reachable"]:
        raise SystemExit(f"Nothing answers at {base.base_url}: start the server, then `python -m graphrag.bench check "
                         f"{spec}`.{' ' + server['error'] if server['error'] else ''}")
    running, wanted = served_file(server), profile.get("file")
    if running and wanted and running != wanted:
        raise SystemExit(f"The server runs {running}, the profile names {wanted}: they must match, so that no other "
                         f"model's answers are measured or cached under this profile.")
    # The served file and build join the cache tag; --fresh adds the run's name, so nothing earlier is reused.
    endpoint = profile_endpoint(profile, served="|".join(filter(None, [_served(server), f"run={name}" if fresh else ""]))
                                or None)
    register(spec, endpoint)
    k1_chunks = _k1_chunks(k1)
    _preflight(suite, k1_chunks, no_embeddings)
    path = _results() / f"{name}.bench.json"
    identity = {"spec": spec, "suite": suite, "model": profile["model"], "base_url": endpoint.base_url,
                "served": _served(server), "options": {"k1": k1_chunks, "no_embeddings": no_embeddings, "fresh": fresh}}
    planned = steps(suite, name, spec, profile["model"], bool(k1_chunks), no_embeddings)
    if path.is_file():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["identity"] != identity:
            changed = ", ".join(k for k in identity if manifest["identity"].get(k) != identity[k])
            raise SystemExit(f"A run named {name} exists with a different {changed}. Give another --name; a resumed run "
                             f"must use the same model, server and options.")
        print(f"Resuming {name}: {sum(s['status'] == 'done' for s in manifest['steps'])} of "
              f"{len(manifest['steps'])} steps done.", flush=True)
    else:
        manifest = {"name": name, "identity": identity, "profile": {k: v for k, v in profile.items() if k != "spec"},
                    "model": profile["model"], "endpoint": {"name": endpoint.name, "base_url": endpoint.base_url,
                                                            "hosted": endpoint.hosted},
                    "server": {"models": server["models"], "props": server["props"]},
                    "date": datetime.now().date().isoformat(), "started": _now(), "finished": None,
                    "one_request_at_a_time": True, "steps": planned}
    _results().mkdir(parents=True, exist_ok=True)

    def save() -> None:
        manifest["updated"], manifest["totals"] = _now(), totals(manifest)
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")

    modules = {"baseline": baseline, "events": events, "coordinator": coordinator}
    for step in manifest["steps"]:
        if step["status"] == "done" and (_results() / f"{step['run']}.json").is_file():
            print(f"[{step['id']}] done already: {step['run']}", flush=True)
            continue
        step.update(status="started", started=_now(), error=None)
        save()
        print(f"[{step['id']}] {step['experiment']}: python -m graphrag.{step['command']} {' '.join(step['argv'])}",
              flush=True)
        started = time.perf_counter()
        try:
            # The coordinator reads its roles: the profile serves frame and answer for the length of the step.
            with _environment(GRAPHRAG_PROFILE=spec, GRAPHRAG_K1_CHUNKS=k1_chunks):
                modules[step["command"]].main(step["argv"])
        except (Exception, KeyboardInterrupt, SystemExit) as error:
            step.update(status="stopped", error=f"{type(error).__name__}: {error}"[:500])
            save()
            raise SystemExit(f"Step {step['id']} stopped ({step['error']}). Run the same command again to resume: "
                             f"finished steps are skipped and answered questions come from the cache.") from error
        step.update(status="done", finished=_now(), wall_seconds=round(time.perf_counter() - started, 1))
        save()
    manifest["finished"] = _now()
    save()
    return manifest


def print_run(manifest: dict) -> None:
    t = manifest["totals"]
    print(f"\n{manifest['name']}: {len(manifest['steps'])} steps, {t['questions']} questions, {t['calls']} calls "
          f"({t['cached_calls']} from the cache), {t['prompt_tokens']:,} prompt and {t['completion_tokens']:,} completion "
          f"tokens, {t['seconds']} s and US${t['cost_usd']:.4f} paid now"
          + (f" ({t['cached_seconds']} s and US${t['cached_cost_usd']:.4f} earlier, for the cached calls)"
             if t["cached_calls"] else "") + ".")
    print(f"Written: {(_results() / (manifest['name'] + '.bench.json'))}. "
          f"Next: python -m graphrag.bench compare {manifest['name']}")


# ---- compare -----------------------------------------------------------------------------------------------------

def _recorded_key(result: dict) -> tuple[str, bool]:
    """A run written by the commands themselves: its endpoint:model, and whether that endpoint is hosted."""
    if "roles" in result:
        models = sorted({f"{r['endpoint']}:{r['model']}" for r in result["roles"].values()})
    else:
        models = (result.get("cost") or {}).get("models") or [f"{result.get('endpoint')}:{result.get('model')}"]
    key = " + ".join(models)
    return key, "openrouter" in key


def load_run(name: str) -> dict:
    """A bench run (`<name>.bench.json`) with its finished steps, or a single run file of the existing commands."""
    path = _results() / f"{name}.bench.json"
    if path.is_file():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        profile = manifest["profile"]
        done = [s for s in manifest["steps"] if s["status"] == "done" and (_results() / f"{s['run']}.json").is_file()]
        return {"name": name, "profile": profile["name"], "key": profile.get("compare_as") or profile["name"],
                "hosted": profile["hosted"], "providers": (manifest.get("totals") or {}).get("providers", []),
                "date": manifest.get("date"), "manifest": manifest,
                "unfinished": [s["id"] for s in manifest["steps"] if s not in done],
                "steps": [{"id": s["id"], "result": json.loads((_results() / f"{s['run']}.json").read_text(
                    encoding="utf-8"))} for s in done]}
    path = _results() / f"{name}.json"
    if not path.is_file():
        raise SystemExit(f"No run {name!r} in {_results()}: give a bench run name or a run file name.")
    result = json.loads(path.read_text(encoding="utf-8"))
    key, hosted = _recorded_key(result)
    return {"name": name, "profile": f"recorded {key}", "key": key, "hosted": hosted,
            "providers": sorted({p for ledger in _ledgers(result) for p in ledger.get("providers") or []}),
            "date": None, "manifest": None, "unfinished": [], "steps": [{"id": name, "result": result}]}


def _score(rows: list[dict]) -> tuple[int, int]:
    """Correct answers and wrong answers (an answer with a value the gold does not have)."""
    return (sum(bool(r["correct"]) for r in rows),
            sum(r["status"] == "answered" and not r.get("no_wrong_values", True) for r in rows))


def lines(step_id: str, result: dict) -> list[dict]:
    """A run file as lines of a comparison: one per question set, with its cost per question."""
    ledgers = _ledgers(result)
    total = {key: sum(ledger.get(key, 0) for ledger in ledgers) for key in TOTALS}
    # Calls answered from the cache before their seconds were kept (runs before the model socket) count 0 s.
    approximate = total["cached_calls"] > 0 and not any("cached_seconds" in ledger for ledger in ledgers)
    seconds, cost = total["seconds"] + total["cached_seconds"], total["cost_usd"] + total["cached_cost_usd"]
    if result.get("retriever") != "coordinator":
        correct, wrong = _score(result["rows"])
        kind = "event graph" if "planner_tokens" in result else \
            f"{result['retriever']}{' + fact sheet' if result.get('fact_sheet') else ''}"
        return [{"step": step_id, "set": result.get("question_set", "prototype"),
                 "pipeline": f"{kind}, {result['pool']}", "questions": len(result["rows"]), "correct": correct,
                 "wrong": wrong, "calls": total["calls"], "prompt": total["prompt_tokens"],
                 "completion": total["completion_tokens"], "seconds": seconds, "cost": cost,
                 "approximate": approximate, "coordinator": False}]
    rows = result["rows"]
    tokens = lambda subset: sum(r["prompt_tokens"] + r["frame_prompt_tokens"] + r["completion_tokens"]
                                + r["frame_completion_tokens"] for r in subset)
    whole = tokens(rows) or 1
    out = []
    for name in dict.fromkeys(r["set"] for r in rows):
        subset = [r for r in rows if r["set"] == name]
        correct, wrong = _score(subset)
        share = tokens(subset) / whole
        line = {"step": step_id, "set": name, "pipeline": f"coordinator, {result['pool']}", "questions": len(subset),
                "correct": correct, "wrong": wrong, "calls": sum(r["calls"] for r in subset),
                "prompt": sum(r["prompt_tokens"] + r["frame_prompt_tokens"] for r in subset),
                "completion": sum(r["completion_tokens"] + r["frame_completion_tokens"] for r in subset),
                # The run's seconds and cost, shared among the sets by tokens: cached calls have no row seconds.
                "seconds": seconds * share, "cost": cost * share, "approximate": approximate, "shared": True,
                "coordinator": True, "rightly_routed": sum(bool(r["rightly_routed"]) for r in subset),
                "fallbacks": sum(bool(r["fallback"]) for r in subset)}
        if any("reasoning_score" in r for r in subset):
            line["reasoning"] = reasoning.summarize(subset)
        out.append(line)
    return out


def table(header: list[str], rows: list[list[Any]], text_columns: int = 2) -> str:
    """A Markdown table, readable in a terminal and pasted as it is into a record. Columns after the first
    `text_columns` hold numbers and are right-aligned."""
    rule = ["---:" if i >= text_columns else "---" for i in range(len(header))]
    return "\n".join("| " + " | ".join(str(c) for c in cells) + " |" for cells in [header, rule, *rows])


def _per(value: float, questions: int, digits: int = 0) -> str:
    return f"{value / questions:,.{digits}f}" if questions else "-"


def groups(runs: list[dict]) -> list[list[dict]]:
    """Runs that may be lined up: the same profile, or a profile declared the same model as recorded runs
    (`compare_as`), and the same hosting. A hosted score is never compared with a local one (D-68)."""
    out: dict[tuple[str, bool], list[dict]] = {}
    for run_ in runs:
        out.setdefault((run_["key"], run_["hosted"]), []).append(run_)
    return list(out.values())


def results_table(group: list[dict]) -> str:
    rows = []
    for run_ in group:
        for step in run_["steps"]:
            for line in lines(step["id"], step["result"]):
                mark = "*" if line["approximate"] else ""
                rows.append([line["set"], f"{run_['name']} ({line['pipeline']})", f"{line['correct']}/{line['questions']}",
                             line["wrong"], _per(line["calls"], line["questions"], 1),
                             _per(line["prompt"], line["questions"]), _per(line["completion"], line["questions"]),
                             _per(line["seconds"], line["questions"], 2) + mark,
                             f"{line['cost'] / line['questions']:.6f}" if line["questions"] else "-"])
    return table(["Question set", "Run", "Correct", "Wrong", "Calls/q", "Prompt tok/q", "Completion tok/q", "s/q",
                  "US$/q"], rows)


def coordinator_table(group: list[dict]) -> tuple[str, list[str]]:
    """The coordinator per question set against the hand-routed run of the same set from the same profile, and how
    often it chose the lane the set was answered from by hand. Returns the table and what could not be lined up."""
    hand: dict[str, tuple[str, dict]] = {}
    for run_ in group:
        for step in run_["steps"]:
            for line in lines(step["id"], step["result"]):
                if not line["coordinator"]:
                    hand.setdefault(line["set"], (run_["name"], line))
    rows, missing = [], []
    for run_ in group:
        for step in run_["steps"]:
            for line in (x for x in lines(step["id"], step["result"]) if x["coordinator"]):
                if "reasoning" in line:
                    r = line["reasoning"]
                    rows.append([line["set"], run_["name"], "no hand-routed lane", f"{r['correct']} (probe)", "-",
                                 f"{line['rightly_routed']}/{line['questions']}",
                                 f"problem found {r['problem_found']}, stated cause found and cited "
                                 f"{r['stated_found_and_cited']}, unsupported claims {r['unsupported_claims']}"])
                    continue
                found = hand.get(line["set"])
                if found is None:
                    missing.append(line["set"])
                hand_score = f"{found[1]['correct']}/{found[1]['questions']} ({found[0]})" if found else "not run"
                difference = f"{line['correct'] - found[1]['correct']:+d}" if found and \
                    found[1]["questions"] == line["questions"] else "-"
                rows.append([line["set"], run_["name"], hand_score, f"{line['correct']}/{line['questions']}", difference,
                             f"{line['rightly_routed']}/{line['questions']}", f"{line['fallbacks']} fallbacks"])
    return table(["Question set", "Coordinator run", "Hand-routed", "Coordinator", "Difference", "Right lane",
                  "Notes"], rows) if rows else "", missing


STAND_IN = "[stub model]"


def stand_in(run_: dict) -> bool:
    """Whether a run was answered by scripts/stub_model_server.py: its replies carry the stand-in's label."""
    return any(STAND_IN in str(row.get("raw_values", "")) + str(row.get("answer_text", "")) + str(row.get("evidence", ""))
               for step in run_["steps"] for row in step["result"].get("rows", []))


def compare(names: list[str]) -> str:
    runs = [load_run(name) for name in names]
    parts, found = [], groups(runs)
    if any(stand_in(r) for r in runs):
        parts.append(f"**Answered by the stand-in server (scripts/stub_model_server.py): "
                     f"{', '.join(r['name'] for r in runs if stand_in(r))}. This proves the wiring, never a score.**")
    if len(found) > 1:
        described = "; ".join(f"{', '.join(r['name'] for r in g)}: {g[0]['profile']} "
                              f"({'hosted' if g[0]['hosted'] else 'our own copy'})" for g in found)
        parts.append(f"**Not comparable: these runs use different models or endpoints** ({described}). Each is shown "
                     f"in its own table and nothing is lined up across them."
                     + (" A hosted score is compared only with a baseline rerun on the same endpoint (D-68)."
                        if any(r["hosted"] for r in runs) else ""))
    for group in found:
        head = group[0]
        parts.append(f"### {head['profile']} ({'hosted' if head['hosted'] else 'our own copy'})")
        providers = sorted({p for r in group for p in r["providers"]})
        if head["hosted"] and providers:
            parts.append(f"Providers that answered: {', '.join(providers)}."
                         + (" More than one: scores may differ by provider." if len(providers) > 1 else ""))
        for run_ in group:
            if run_["unfinished"]:
                parts.append(f"{run_['name']} has unfinished steps, not shown: {', '.join(run_['unfinished'])}.")
        parts.append(results_table(group))
        coordinated, missing = coordinator_table(group)
        if coordinated:
            parts.append("Coordinator against the hand-routed scores of the same profile:\n\n" + coordinated)
        if missing:
            parts.append(f"No hand-routed run from this profile for {', '.join(dict.fromkeys(missing))}: run "
                         f"`python -m graphrag.bench run <profile> --suite full`. The coordinator is not compared with "
                         f"another profile's scores.")
    if any(line["approximate"] for run_ in runs for step in run_["steps"] for line in lines(step["id"], step["result"])):
        parts.append("\\* Some calls came from the cache before their seconds were kept; they count 0 s.")
    parts.append("Seconds and cost per question include calls answered from the cache, at what they took when made. "
                 "A coordinator run's seconds and cost are shared among its question sets by tokens.")
    return "\n\n".join(parts)


# ---- command line ------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="a preflight of a few calls: is this model usable here?")
    r = sub.add_parser("run", help="run the measurement suite, one request at a time; run again to resume")
    for p in (c, r):
        p.add_argument("profile", help="a profile name (configs/graphrag/models/), a profile file, or endpoint:model")
    r.add_argument("--suite", choices=("quick", "full"), default="quick",
                   help="quick: the prototype's 31 questions; full: hand-routed sets, coordinator (E33), K1 (E32), "
                        "reasoning probe (E34)")
    r.add_argument("--name", help="the run's name; by default bench_<profile>_<suite>")
    r.add_argument("--k1", metavar="PATH", help="a K1 package folder or its chunks.jsonl: daily reports and events "
                                                "from it, and the E32 runs")
    r.add_argument("--no-embeddings", action="store_true",
                   help="per-well BM25 instead of fusion, for a machine without the embedding server")
    r.add_argument("--fresh", action="store_true", help="reuse no earlier cached answer (a resume still reuses its own)")
    m = sub.add_parser("compare", help="one table across runs; runs of different profiles are never lined up")
    m.add_argument("runs", nargs="+", help="bench run names or run file names under graphrag/results/")
    args = parser.parse_args(argv)
    if args.command == "check":
        sys.exit(print_check(args.profile, check(args.profile)))
    if args.command == "run":
        print_run(run(args.profile, args.suite, args.name, args.k1, args.no_embeddings, args.fresh))
    else:
        print(compare(args.runs))


if __name__ == "__main__":
    main()
