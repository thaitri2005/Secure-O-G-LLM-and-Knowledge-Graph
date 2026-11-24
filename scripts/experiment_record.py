"""A draft experiment record from finished bench runs, in the house style (docs/experiments/E28-event-graph.md).

    python scripts/experiment_record.py E33 bench_qwen3-8b.local_full --title "The coordinator on the pooled questions"
    python scripts/experiment_record.py E32 bench_qwen3-8b.local_full bench_qwen3-8b.openrouter_full --out draft.md

The header and the tables are filled from the runs (`python -m graphrag.bench run`). The question, what was learned
and the limits are left as marked blanks for a person: interpreting a result is not a script's job. It writes
docs/experiments/E<n>-<slug>.md, or --out, and never adds a row to the register (docs/experiments/README.md): add it
by hand once the prose is written.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from graphrag import bench  # noqa: E402

BLANK = "**TO WRITE (a person):**"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "draft"


def _server(run: dict) -> str:
    manifest = run["manifest"] or {}
    props = (manifest.get("server") or {}).get("props")
    if not props:
        return "settings not reported by the server" if not run["hosted"] else "hosted: no server settings"
    return (f"llama.cpp {props.get('build_info') or '(build not reported)'}, model file "
            f"{bench.served_file(manifest['server'])}, n_ctx {props.get('n_ctx')}, {props.get('total_slots')} slot(s)")


def _model(run: dict) -> str:
    manifest = run["manifest"]
    if manifest is None:
        return f"`{run['key']}`, as recorded in its run file"
    profile = manifest["profile"]
    providers = run["providers"]
    return (f"`{profile['name']}`: `{manifest['model']}` at {manifest['endpoint']['base_url']} "
            f"({'hosted, provider ' + (', '.join(providers) or 'not reported') if run['hosted'] else 'our own copy'}); "
            f"{_server(run)}; thinking off: {profile.get('thinking_off', 'not stated in the profile')}; "
            f"one request at a time")


def _totals(runs: list[dict]) -> str:
    rows = []
    for run in runs:
        t = (run["manifest"] or {}).get("totals")
        if not t:
            continue
        rows.append([run["name"], t["questions"], t["calls"], t["cached_calls"], f"{t['prompt_tokens']:,}",
                     f"{t['completion_tokens']:,}", f"{t['seconds'] + t['cached_seconds']:,.1f}",
                     f"{t['cost_usd'] + t['cached_cost_usd']:.4f}"])
    return bench.table(["Run", "Questions", "LLM calls", "From the cache", "Prompt tokens", "Completion tokens",
                        "Seconds", "US$"], rows, text_columns=1) if rows else "No bench totals: these are run files of the commands."


def _commands(runs: list[dict]) -> str:
    """The bench command of each run and the commands its steps ran, to reproduce it."""
    out = []
    for run in runs:
        manifest = run["manifest"]
        if manifest is None:
            out.append(f"# {run['name']}: a run file of the commands; its command is not recorded")
            continue
        identity, options = manifest["identity"], manifest["identity"]["options"]
        out.append(f"python -m graphrag.bench run {identity['spec']} --suite {identity['suite']} --name {run['name']}"
                   + (f" --k1 {options['k1']}" if options.get("k1") else "")
                   + (" --no-embeddings" if options.get("no_embeddings") else "")
                   + (" --fresh" if options.get("fresh") else ""))
        out += [f"#   {s['id']}: python -m graphrag.{s['command']} {' '.join(s['argv'])}" for s in manifest["steps"]]
    return "```powershell\n" + "\n".join(out) + "\n```"


def record(number: str, names: list[str], title: str) -> str:
    runs = [bench.load_run(name) for name in names]
    dates = sorted({r["date"] for r in runs if r["date"]})
    sets = sorted({line["set"] for run in runs for step in run["steps"] for line in bench.lines(step["id"], step["result"])})
    commands = sorted({s["command"] for run in runs for s in (run["manifest"] or {}).get("steps", [])})
    k1 = sorted({str((run["manifest"] or {}).get("identity", {}).get("options", {}).get("k1")) for run in runs} - {"None"})
    outputs = [f"`{s['run']}.json`" for run in runs for s in (run["manifest"] or {}).get("steps", [])
               if s["status"] == "done"] or [f"`{run['name']}.json`" for run in runs]
    warning = ""
    if any(bench.stand_in(run) for run in runs):
        warning = ("\n> **These runs were answered by the stand-in server (scripts/stub_model_server.py). They prove the "
                   "wiring, not quality: do not register them or quote their scores.**\n")
    header = [
        ("Date", ", ".join(dates) or "not recorded"),
        ("Question", f"{BLANK} what this measurement asks"),
        ("Requirement", f"{BLANK} the decisions and log entries it answers to"),
        ("Input", "K1 package " + ", ".join(f"`{p}`" for p in k1) if k1 else
         "Committed K1 version 0 chunks and the corpus release (daily reports)"),
        ("Code", "`graphrag/bench.py`" + "".join(f", `graphrag/{c}.py`" for c in commands)),
        ("Gold data", ", ".join(f"`{s}`" for s in sets) + ". Written by the team; **no drilling expert has reviewed "
                                                          "them** (B-D22)"),
        ("Models", "<br>".join(_model(run) for run in runs)),
        ("Outputs", "[`graphrag/results/`](../../graphrag/results/): " + ", ".join(outputs)),
        ("Status", f"Draft, tables written by `scripts/experiment_record.py` on {date.today().isoformat()}; "
                   f"prose not written"),
    ]
    lines = [f"# {number}: {title or BLANK + ' title'}", warning, "| | |", "|---|---|"]
    lines += [f"| **{key}** | {value} |" for key, value in header]
    lines += ["", "## How it was run", "", f"{BLANK} what the setup measures, in a few numbered steps.", "",
              _commands(runs), "",
              "## Results", "", bench.compare(names), "", "## Cost", "", _totals(runs), "",
              "## What was learned", "", f"{BLANK} what the tables show, in numbered points, each with its numbers.", "",
              "## Limits", "", "- The questions were written by the team; none is expert-validated (B-D22).",
              f"- {BLANK} anything else that limits these results (one well, runs made once, provider changes).", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("number", help="the experiment number, such as E33")
    parser.add_argument("runs", nargs="+", help="bench run names (or run file names) under graphrag/results/")
    parser.add_argument("--title", default="", help="the record's title")
    parser.add_argument("--out", help="where to write; by default docs/experiments/<number>-<title as a slug>.md")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args(argv)
    out = Path(args.out) if args.out else ROOT / "docs/experiments" / f"{args.number}-{_slug(args.title)}.md"
    if out.exists() and not args.force:
        raise SystemExit(f"{out} exists: give --out or --force.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(record(args.number, args.runs, args.title), encoding="utf-8", newline="\n")
    print(f"wrote {out}. Fill in the parts marked TO WRITE, then add the row to docs/experiments/README.md by hand.")


if __name__ == "__main__":
    main()
