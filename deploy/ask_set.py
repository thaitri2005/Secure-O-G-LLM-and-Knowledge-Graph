"""Ask a whole question set through a running application and score the answers.

    python deploy/ask_set.py --url http://127.0.0.1:8088 --user team --questions prototype --name E32_stores_prototype
    python deploy/ask_set.py --url https://kg.example.org --user team --questions graphrag/gold/pilot_v1.json --name pilot_v1_app

This is the measurement of the application as people use it: the proxy, the backend, the stores and the model, one
question at a time. The questions and their gold are those `python -m graphrag.coordinator answer` takes, and the
score is the same (`graphrag.scoring`), so the two results compare. The password comes from `--password` or
SMOKE_PASSWORD. Every question asked this way is written to the application's question log, like any other.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graphrag.coordinator import pooled, question_set  # noqa: E402
from graphrag.scoring import score_answer  # noqa: E402

RESULTS = ROOT / "graphrag/results"


def call(url: str, auth: str, body: dict | None = None, timeout: float = 1200.0) -> tuple[int, dict]:
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": auth, "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # the application, not through a web proxy
    try:
        with opener.open(request, timeout=timeout) as reply:
            return reply.status, json.loads(reply.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def row_of(q: dict, expected: list[dict], status: int, out: dict, seconds: float) -> dict:
    """One scored row. A question the application could not answer (busy, model down) is wrong, and says why."""
    if status != 200:
        return {"id": q["id"], "set": q["set"], "question": q["question"], "correct": False, "status": "error",
                "http": status, "code": out.get("code"), "values": [], "lanes": [], "calls": 0, "prompt_tokens": 0,
                "completion_tokens": 0, "seconds": round(seconds, 1)}
    values = [a["value"] for a in out["answers"]]
    cost = out["cost"]
    return {"id": q["id"], "set": q["set"], "question": q["question"], "status": out["status"], "values": values,
            "lanes": out["lanes"], "fallback": out["fallback"], "answered_from": out["answered_from"],
            "question_id": out["id"], **score_answer(q, expected, "answered" if values else out["status"], values),
            "calls": cost["calls"], "prompt_tokens": cost["prompt_tokens"], "completion_tokens": cost["completion_tokens"],
            "seconds": round(seconds, 1)}


def summarize(rows: list[dict]) -> dict:
    def part(subset: list[dict]) -> dict:
        mean = lambda key: round(sum(r[key] for r in subset) / len(subset), 1)
        return {"questions": len(subset), "correct": f"{sum(r['correct'] for r in subset)}/{len(subset)}",
                "errors": sum(r["status"] == "error" for r in subset), "calls_per_question": mean("calls"),
                "prompt_tokens": mean("prompt_tokens"), "completion_tokens": mean("completion_tokens"),
                "seconds": mean("seconds")}

    return {**part(rows), "by_set": {name: part([r for r in rows if r["set"] == name])
                                     for name in dict.fromkeys(r["set"] for r in rows)}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--user", default="team")
    parser.add_argument("--password", default=os.environ.get("SMOKE_PASSWORD", ""))
    parser.add_argument("--questions", nargs="+", type=question_set, required=True)
    parser.add_argument("--mode", choices=("allow_fallback", "exact"), default="allow_fallback")
    parser.add_argument("--name", required=True, help="result file name under graphrag/results/")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    auth = "Basic " + base64.b64encode(f"{args.user}:{args.password}".encode()).decode()
    status, health = call(f"{base}/v1/health", auth, timeout=30)
    if status != 200:
        raise SystemExit(f"{base}/v1/health answered {status}: is the address and the password right?")
    questions, gold = pooled(args.questions)
    rows = []
    for q in questions:
        started = time.perf_counter()
        status, out = call(f"{base}/v1/questions", auth, {"question": q["question"], "mode": args.mode})
        row = row_of(q, [gold[g] for g in q["gold"]], status, out, time.perf_counter() - started)
        rows.append(row)
        print(f"{q['id']:<28} {'OK ' if row['correct'] else 'BAD'} {'+'.join(row['lanes']):<20} {row['status']} {row['values']}",
              flush=True)
    result = {"question_set": args.questions, "mode": args.mode, "through": "the application's API", "url": base,
              "health": health, **summarize(rows), "rows": rows}
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{args.name}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("rows", "health")}, indent=2))
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
