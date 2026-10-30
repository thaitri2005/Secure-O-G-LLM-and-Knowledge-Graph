"""EDC (clear-nus/edc @ 02aad17) minitest on LM Studio, scored by EDC's own WebNLG evaluator.

    . ./scripts/onprem_env.ps1
    .venvs/edc/Scripts/python.exe scripts/upstream/run_edc.py --dry-run     # no model calls
    .venvs/edc/Scripts/python.exe scripts/upstream/run_edc.py               # needs approval

Upstream source is untouched. Two runtime shims, both set here:
  * llm_utils.is_model_openai -> True for --model (upstream checks a provider-specific model-name substring,
    otherwise it downloads the model from HF and runs it with transformers);
  * the module-level openai client points at LM Studio (base_url, timeout).
A wall-clock watchdog stops the run because upstream retries failed calls forever.
"""

import _onprem
import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = _onprem.PROJECT_ROOT
EDC_ROOT = PROJECT_ROOT / "third_party" / "edc"
sys.path.insert(0, str(EDC_ROOT))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, default=PROJECT_ROOT / "data" / "benchmarks" / "webnlg" / "webnlg_30.txt")
    p.add_argument("--reference", type=Path, default=PROJECT_ROOT / "data" / "benchmarks" / "webnlg" / "webnlg_30.ref.txt")
    p.add_argument("--dataset", default="webnlg", help="upstream few-shot folder and schema name")
    p.add_argument("--model", default="qwen3.6-35b-a3b", help="LM Studio model id")
    p.add_argument("--embedder", default="sentence-transformers/all-MiniLM-L6-v2",
                   help="replaces upstream default intfloat/e5-mistral-7b-instruct (7B)")
    p.add_argument("--out", type=Path, default=PROJECT_ROOT / "runs" / "upstream" / "edc" / "webnlg_30")
    p.add_argument("--limit", type=int, default=None, help="first N docs only (reference is cut to match)")
    p.add_argument("--max-minutes", type=float, default=120.0)
    p.add_argument("--dry-run", action="store_true", help="imports, config, data and evaluator only")
    args = p.parse_args()
    args.out = args.out.resolve()
    return args


def edc_config(args: argparse.Namespace) -> dict:
    """Same keys as third_party/edc/run.py, with absolute paths and local models."""
    t = EDC_ROOT / "prompt_templates"
    f = EDC_ROOT / "few_shot_examples" / args.dataset
    cfg = {
        "oie_llm": args.model,
        "oie_prompt_template_file_path": t / "oie_template.txt",
        "oie_few_shot_example_file_path": f / "oie_few_shot_examples.txt",
        "sd_llm": args.model,
        "sd_prompt_template_file_path": t / "sd_template.txt",
        "sd_few_shot_example_file_path": f / "sd_few_shot_examples.txt",
        "sc_llm": args.model,
        "sc_embedder": args.embedder,
        "sc_prompt_template_file_path": t / "sc_template.txt",
        "sr_adapter_path": None,
        "sr_embedder": args.embedder,
        "oie_refine_prompt_template_file_path": t / "oie_r_template.txt",
        "oie_refine_few_shot_example_file_path": f / "oie_few_shot_refine_examples.txt",
        "ee_llm": args.model,
        "ee_prompt_template_file_path": t / "ee_template.txt",
        "ee_few_shot_example_file_path": f / "ee_few_shot_examples.txt",
        "em_prompt_template_file_path": t / "em_template.txt",
        "target_schema_path": EDC_ROOT / "schemas" / f"{args.dataset}_schema.csv",
        "enrich_schema": False,
        "loglevel": logging.INFO,
    }
    missing = [str(v) for v in cfg.values() if isinstance(v, Path) and not v.exists()]
    if missing:
        raise SystemExit(f"missing upstream files: {missing}")
    return {k: str(v) if isinstance(v, Path) else v for k, v in cfg.items()}


def evaluate(prediction: Path, reference: Path, workdir: Path) -> str:
    """Run upstream evaluate/evaluation_script.py; it writes ./result_xmls under workdir."""
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(EDC_ROOT / "evaluate" / "evaluation_script.py"),
           "--edc_output", str(prediction.resolve()), "--reference", str(reference.resolve())]
    done = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise SystemExit(f"evaluator failed:\n{done.stderr[-2000:]}")
    (workdir / "eval.txt").write_text(done.stdout, encoding="utf-8")
    return done.stdout


def install_shims(model: str, base_url: str, api_key: str) -> dict:
    import openai
    import edc.utils.llm_utils as llm_utils

    os.environ["OPENAI_KEY"] = api_key  # read by llm_utils.openai_chat_completion
    openai.base_url = base_url.rstrip("/") + "/"
    openai.timeout = 600.0
    llm_utils.is_model_openai = lambda name: name == model

    stats = {"llm_calls": 0, "llm_seconds": 0.0}
    upstream_call = llm_utils.openai_chat_completion

    def counted(*a, **kw):
        start = time.time()
        try:
            return upstream_call(*a, **kw)
        finally:
            stats["llm_calls"] += 1
            stats["llm_seconds"] += time.time() - start

    llm_utils.openai_chat_completion = counted
    return stats


def dry_run(args: argparse.Namespace, cfg: dict) -> None:
    from edc.edc_framework import EDC
    from sentence_transformers import SentenceTransformer

    edc = EDC(**cfg)  # parses the target schema CSV; loads no model
    texts = args.input.read_text(encoding="utf-8").splitlines()
    refs = args.reference.read_text(encoding="utf-8").splitlines()
    assert len(texts) == len(refs), (len(texts), len(refs))
    SentenceTransformer(args.embedder)  # offline cache check, CPU only
    gold_vs_gold = evaluate(args.reference, args.reference, args.out.parent / "dry_run_eval")
    print(json.dumps({"schema_relations": len(edc.schema), "docs": len(texts),
                      "embedder_cached": True, "evaluator_tail": gold_vs_gold.strip().splitlines()[-3:]},
                     indent=2))


def main() -> None:
    args = parse_args()
    base_url, api_key = _onprem.local_endpoint()
    cfg = edc_config(args)
    if args.dry_run:
        dry_run(args, cfg)
        return
    if args.out.exists():
        raise SystemExit(f"{args.out} exists; EDC.extract_kg would exit(). Pick a new --out.")

    import _nothink

    net_log = _onprem.guard_network(f"net_edc_{args.out.name}")
    llm_log = args.out.parent / f"llm_calls_{args.out.name}.jsonl"
    base_url = _nothink.start(base_url, llm_log)
    stats = install_shims(args.model, base_url, api_key)
    from edc.edc_framework import EDC

    def watchdog() -> None:
        print(f"watchdog: exceeded {args.max_minutes} min, stopping", flush=True)
        os._exit(3)

    timer = threading.Timer(args.max_minutes * 60, watchdog)
    timer.daemon = True
    timer.start()

    texts = args.input.read_text(encoding="utf-8").splitlines(keepends=True)[: args.limit]
    refs = args.reference.read_text(encoding="utf-8").splitlines(keepends=True)[: len(texts)]
    start = time.time()
    EDC(**cfg).extract_kg(texts, str(args.out), refinement_iterations=0)
    stats["wall_seconds"] = round(time.time() - start, 1)
    timer.cancel()

    reference = args.out / "reference.txt"
    reference.write_text("".join(refs), encoding="utf-8")
    report = evaluate(args.out / "iter0" / "canon_kg.txt", reference, args.out)
    summary = {"model": args.model, "embedder": args.embedder, "docs": len(texts), **stats,
               "proxy": _nothink.summarize(llm_log), "llm_log": str(llm_log.relative_to(PROJECT_ROOT)),
               "net_log": str(net_log.relative_to(PROJECT_ROOT)), "evaluator_tail": report.strip().splitlines()[-3:]}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
