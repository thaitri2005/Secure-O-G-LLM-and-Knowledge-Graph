"""Checks a running deployment from outside, through the proxy, as a user would reach it. Standard library only.

    python deploy/smoke_test.py --url https://kg.example.org --user team --password '<the shared password>'
    python deploy/smoke_test.py --url http://127.0.0.1:8088 --user team --password local-smoke-test --expect-stub

    python deploy/smoke_test.py --url https://kg.example.org --user team --quick       # what the monitor runs

Six checks, in order, each printed with its result; the exit code is 1 when any fails:

1. the gate: a request without the password is refused (401);
2. the frontend: the start page loads with the password;
3. health: GET /v1/health answers and names the data and the models;
4. ready: GET /v1/ready says the model endpoint and the question log answer;
5. one question: POST /v1/questions returns an answer (with `--expect-stub`, one that says it is the stub model's);
6. one feedback: POST /v1/questions/<id>/feedback is stored.

`--quick` stops after the fourth: it asks nothing of the model and writes nothing to the question log, so it can run
every few minutes (deploy/watch.sh).

The question and its feedback go into the question log like any other, with "smoke test" as the comment, so they
can be told apart (and left out of any count). The password can also come from SMOKE_PASSWORD.
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

QUESTION = "What total depth did well AK-3 reach?"


def request(url: str, auth: str | None, body: dict | None = None, timeout: float = 30) -> tuple[int, bytes]:
    headers = {"Accept": "application/json, text/html"}
    if auth:
        headers["Authorization"] = f"Basic {auth}"
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode("utf-8"), "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="the proxy's address, e.g. https://kg.example.org")
    parser.add_argument("--user", default="team")
    parser.add_argument("--password", default=os.environ.get("SMOKE_PASSWORD"))
    parser.add_argument("--question", default=QUESTION)
    parser.add_argument("--timeout", type=float, default=300, help="seconds for the question; a real model is slow")
    parser.add_argument("--quick", action="store_true", help="the first four checks only: no question is asked")
    parser.add_argument("--expect-stub", action="store_true", help="the stub model serves: its label must show")
    args = parser.parse_args(argv)
    if not args.password:
        parser.error("give --password or set SMOKE_PASSWORD")
    base = args.url.rstrip("/")
    auth = base64.b64encode(f"{args.user}:{args.password}".encode("utf-8")).decode("ascii")
    failures = 0

    def check(name: str, ok: bool, detail: str) -> bool:
        nonlocal failures
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}", flush=True)
        return ok

    status, _ = request(f"{base}/v1/health", None)
    check("gate", status == 401, f"without the password GET /v1/health gives {status} (want 401)")

    status, page = request(f"{base}/", auth)
    check("frontend", status == 200 and b"<html" in page.lower(), f"GET / gives {status}, {len(page)} bytes")

    status, raw = request(f"{base}/v1/health", auth)
    health = json.loads(raw) if status == 200 else {}
    check("health", status == 200 and "data" in health,
          f"{status}, data {json.dumps(health.get('data'))}, models {json.dumps(health.get('models'))}")

    status, raw = request(f"{base}/v1/ready", auth)
    try:
        ready = json.loads(raw)
    except ValueError:
        ready = {}
    check("ready", status == 200 and ready.get("ready") is True, f"{status}, checks {json.dumps(ready.get('checks'))}")
    if args.quick:
        print(f"{4 - failures} of 4 checks passed", flush=True)
        return 1 if failures else 0

    started = time.perf_counter()
    status, raw = request(f"{base}/v1/questions", auth, {"question": args.question}, timeout=args.timeout)
    seconds = time.perf_counter() - started
    answer = json.loads(raw) if status == 200 else {}
    text = answer.get("answer_text") or ""
    ok = status == 200 and bool(answer.get("id")) and answer.get("status") in ("answered", "not_stated", "not_found_in_graph")
    if args.expect_stub:
        ok = ok and text.startswith("[stub model]")
    check("question", ok, f"{status} in {seconds:.1f} s: status {answer.get('status')}, lanes {answer.get('lanes')}, "
                          f"answer {text!r}, {len(answer.get('citations') or [])} citations, cost {answer.get('cost')}"
                          + ("" if status == 200 else f", body {raw[:300]!r}"))

    if answer.get("id"):
        status, raw = request(f"{base}/v1/questions/{answer['id']}/feedback", auth,
                              {"verdict": "right", "comment": "smoke test"})
        check("feedback", status == 200, f"{status} {raw[:200].decode('utf-8', 'replace')}")
    else:
        check("feedback", False, "skipped: the question gave no ID")

    print(f"{6 - failures} of 6 checks passed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
