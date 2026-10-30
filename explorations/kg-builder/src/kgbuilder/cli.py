"""Command-line interface for the on-premises KG builder (`kgb`)."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from kgbuilder.runtime import onprem


def main(argv: list | None = None) -> int:
    """Load the local environment, install the guard, and dispatch CLI commands."""
    onprem.load_env()
    args = list(sys.argv[1:] if argv is None else argv)
    if sys.flags.hash_randomization or not getattr(sys.flags, "utf8_mode", 1):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = "0"
        env["PYTHONUTF8"] = "1"
        env["PYTHONPATH"] = str(onprem.PROJECT_ROOT / "src")
        return subprocess.call([sys.executable, "-m", "kgbuilder", *args], env=env)
    core_log = onprem.guard_network(onprem.PROJECT_ROOT / ".cache" / "kgb" / "net" / f"core_{os.getpid()}.jsonl")
    import json
    import logging
    import traceback
    from pathlib import Path
    from kgbuilder.core.config import ConfigError, KgbError, from_resolved, project_path, load_config, load_demo
    from kgbuilder.build import pipeline
    from kgbuilder.evaluation import evaluate

    logger = logging.getLogger("kgb")
    logger.setLevel(logging.INFO)
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setLevel(logging.INFO)
    stdout.addFilter(lambda record: record.levelno < logging.WARNING)
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setLevel(logging.WARNING)
    logger.addHandler(stdout)
    logger.addHandler(stderr)
    parser = argparse.ArgumentParser(prog="kgb")
    subcommands = parser.add_subparsers(dest="command", required=True)
    preflight_parser = subcommands.add_parser("preflight")
    preflight_parser.add_argument("--config", required=True)
    preflight_parser.add_argument("--probe", action="store_true")
    preflight_parser.add_argument("--set", action="append", default=[], dest="sets")
    build_parser = subcommands.add_parser("build")
    build_parser.add_argument("--config", required=True)
    build_parser.add_argument("--ablation", choices=["A0", "A1", "A2", "A3", "A4", "A5"])
    build_parser.add_argument("--mock", action="store_true")
    build_parser.add_argument("--set", action="append", default=[], dest="sets")
    build_parser.add_argument("--out")
    build_parser.add_argument("--overwrite", action="store_true")
    eval_parser = subcommands.add_parser("eval")
    eval_modes = eval_parser.add_subparsers(dest="eval_mode", required=True)
    for mode in ("showcase", "webnlg"):
        eval_modes.add_parser(mode).add_argument("--run", required=True)
    qa_parser = eval_modes.add_parser("qa")
    qa_parser.add_argument("--config", required=True)
    qa_parser.add_argument("--mock", action="store_true")
    qa_parser.add_argument("--set", action="append", default=[], dest="sets")
    qa_parser.add_argument("--out")
    qa_parser.add_argument("--overwrite", action="store_true")
    wells_parser = eval_modes.add_parser("wells")
    for key in ("config", "run", "corpus", "out"):
        wells_parser.add_argument("--" + key, required=True)
    for key in ("labels", "rules", "gold", "gold-config", "baseline"):
        wells_parser.add_argument("--" + key)
    wells_parser.add_argument("--overwrite", action="store_true")
    wells_parser.add_argument("--split", choices=["test", "dev"], default="test")
    attribution_parser = eval_modes.add_parser("attribution")
    for key in ("config", "run", "corpus", "gold-config", "out"):
        attribution_parser.add_argument("--" + key, required=True)
    attribution_parser.add_argument("--split", choices=["dev", "test"], required=True)
    attribution_parser.add_argument("--export", choices=["full", "strict"], default="full")
    attribution_parser.add_argument("--lexicon", default="configs/domains/bsee/bsee_literals.yaml")
    attribution_parser.add_argument("--overwrite", action="store_true")
    run_parser = subcommands.add_parser("run")
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument("--mock", action="store_true")
    run_parser.add_argument("--only", action="append", default=[])
    run_parser.add_argument("--set", action="append", default=[], dest="sets")
    run_parser.add_argument("--out")
    run_parser.add_argument("--overwrite", action="store_true")
    fixtures_parser = subcommands.add_parser("fixtures")
    fixtures_parser.add_argument("--from", required=True, dest="source")
    fixtures_parser.add_argument("--to", required=True, dest="target")
    fixtures_parser.add_argument("--overwrite", action="store_true")
    fetch_parser = subcommands.add_parser("fetch")
    fetch_modes = fetch_parser.add_subparsers(dest="fetch_mode", required=True)
    bsee_parser = fetch_modes.add_parser("bsee")
    bsee_parser.add_argument("--config", required=True)
    bsee_parser.add_argument("--from-dir", required=True)
    domain_parser = subcommands.add_parser("domain")
    domain_modes = domain_parser.add_subparsers(dest="domain_mode", required=True)
    tables_parser = domain_modes.add_parser("tables")
    tables_parser.add_argument("--config", required=True)
    tables_parser.add_argument("--out", required=True)
    tables_parser.add_argument("--overwrite", action="store_true")
    corpus_parser = domain_modes.add_parser("corpus")
    corpus_parser.add_argument("--config", required=True)
    corpus_parser.add_argument("--out", required=True)
    corpus_parser.add_argument("--overwrite", action="store_true")
    corpus_v2_parser = domain_modes.add_parser("corpus-v2")
    corpus_v2_parser.add_argument("--config", required=True)
    corpus_v2_parser.add_argument("--out", required=True)
    corpus_v2_parser.add_argument("--overwrite", action="store_true")
    split_parser = domain_modes.add_parser("split-corpus")
    for key in ("corpus", "gold-config", "out"):
        split_parser.add_argument("--" + key, required=True)
    split_parser.add_argument("--part", choices=["dev"], required=True)
    split_parser.add_argument("--overwrite", action="store_true")
    link_parser = domain_modes.add_parser("link")
    for key in ("run", "tables", "sources", "policy", "out"):
        link_parser.add_argument("--" + key, required=True)
    link_parser.add_argument("--overwrite", action="store_true")
    labels_parser = domain_modes.add_parser("labels")
    for key in ("config", "gold-config", "tables", "corpus", "out"):
        labels_parser.add_argument("--" + key, required=True)
    labels_parser.add_argument("--overwrite", action="store_true")
    rules_parser = domain_modes.add_parser("rules")
    for key in ("gold-config", "corpus", "out"):
        rules_parser.add_argument("--" + key, required=True)
    rules_parser.add_argument("--overwrite", action="store_true")
    bulk_parser = domain_modes.add_parser("bulk")
    bulk_parser.add_argument("--tables", required=True)
    bulk_parser.add_argument("--out", required=True)
    bulk_parser.add_argument("--overwrite", action="store_true")
    gold_parser = domain_modes.add_parser("gold")
    gold_modes = gold_parser.add_subparsers(dest="gold_mode", required=True)
    for mode in ("prepare", "validate", "seal", "verify", "adjudication-packet", "merge", "agreement", "amend"):
        command = gold_modes.add_parser(mode)
        command.add_argument("--config", required=True)
        if mode == "prepare": command.add_argument("--corpus", required=True)
        if mode == "amend": command.add_argument("--reason", required=True)
        if mode == "validate": command.add_argument("--locations-only", action="store_true")
        if mode in ("validate", "seal"): command.add_argument("--annotator", choices=["annotator_a", "annotator_b", "adjudicator"], required=True)
        if mode == "agreement":
            command.add_argument("--out", required=True)
            command.add_argument("--rules")
    induce_parser = subcommands.add_parser("induce")
    induce_parser.add_argument("--config", required=True)
    induce_parser.add_argument("--run", required=True)
    induce_parser.add_argument("--out", required=True)
    induce_parser.add_argument("--mock", action="store_true")
    induce_parser.add_argument("--set", action="append", default=[], dest="sets")
    induce_parser.add_argument("--overwrite", action="store_true")
    ablate_parser = subcommands.add_parser("ablate")
    ablate_parser.add_argument("--config", required=True)
    ablate_parser.add_argument("--mock", action="store_true")
    ablate_parser.add_argument("--only", action="append", default=[])
    ablate_parser.add_argument("--exclude", action="append", default=[])
    ablate_parser.add_argument("--set", action="append", default=[], dest="sets")
    ablate_parser.add_argument("--out")
    ablate_parser.add_argument("--overwrite", action="store_true")
    analyze_parser = subcommands.add_parser("analyze")
    analyze_source = analyze_parser.add_mutually_exclusive_group(required=True)
    analyze_source.add_argument("--run")
    analyze_source.add_argument("--plan")
    analyze_parser.add_argument("--qa", action="append", default=[])
    analyze_parser.add_argument("--out")
    analyze_parser.add_argument("--overwrite", action="store_true")
    query_parser = subcommands.add_parser("query")
    query_parser.add_argument("--run", required=True)
    query_parser.add_argument("--json", action="store_true")
    query_modes = query_parser.add_subparsers(dest="query_mode", required=True)
    query_modes.add_parser("alias").add_argument("text")
    at_parser = query_modes.add_parser("at")
    at_parser.add_argument("--subject", required=True)
    at_parser.add_argument("--predicate", required=True)
    at_parser.add_argument("--at")
    evidence_parser = query_modes.add_parser("evidence")
    evidence_group = evidence_parser.add_mutually_exclusive_group(required=True)
    evidence_group.add_argument("--statement")
    evidence_group.add_argument("--subject")
    evidence_parser.add_argument("--predicate")
    evidence_parser.add_argument("--object")
    path_parser = query_modes.add_parser("path")
    path_parser.add_argument("--from", required=True, dest="src")
    path_parser.add_argument("--to", required=True, dest="dst")
    path_parser.add_argument("--max-hops", type=int, default=3)
    neo4j_parser = subcommands.add_parser("neo4j")
    neo4j_modes = neo4j_parser.add_subparsers(dest="neo4j_mode", required=True)
    for mode in ("load", "demo"):
        neo_parser = neo4j_modes.add_parser(mode)
        neo_parser.add_argument("--run", required=True)
        neo_parser.add_argument("--set", action="append", default=[], dest="sets")
        if mode == "load":
            neo_parser.add_argument("--wipe", action="store_true")
        else:
            neo_parser.add_argument("--alias", default="International Business Machines")
            neo_parser.add_argument("--subject", default="Alice")
            neo_parser.add_argument("--predicate", default="works_at")
            neo_parser.add_argument("--at", default="2022")
            neo_parser.add_argument("--statement")
            neo_parser.add_argument("--from", dest="src", default="Alan Turing")
            neo_parser.add_argument("--to", dest="dst", default="London")
            neo_parser.add_argument("--json", action="store_true")
    for mode in ("domain-attach", "domain-audit"):
        command = neo4j_modes.add_parser(mode)
        command.add_argument("--set", action="append", default=[], dest="sets")
        for key in (("run", "links") if mode == "domain-attach" else ("tables", "bulk")):
            command.add_argument("--" + key, required=True)
    options = parser.parse_args(args)
    run_dir = None
    def replay_hint(profile):
        return ("LLM replay miss for profile vllm: record a server run and export it with kgb fixtures (docs/runbooks/gpu_server.md)" if profile == "vllm" else
                "LLM replay miss: provide the recorded demo fixture or use --only showcase --set flags.canon=false")
    try:
        if options.command == "analyze":
            from kgbuilder.evaluation import analysis
            if options.plan:
                from kgbuilder.core import text
                from kgbuilder.evaluation import ablation
                source = project_path(options.plan, "plan", True)
                boundary = (onprem.PROJECT_ROOT / "runs").resolve()
                if not source.is_dir() or not source.is_relative_to(boundary) or source == boundary:
                    raise ConfigError("analyze: plan directory must be strictly below runs/")
                if options.out or options.qa:
                    raise ConfigError("analyze --plan: --out and --qa are not applicable")
                report = analysis.plan_cost(source, ablation.request_kind, [onprem.PROJECT_ROOT / p for p in analysis.REFERENCE_RUNS])
                text.write_json(source / "plan_cost.json", report)
                print("model " + " ".join(f"{k}={v}" for k, v in report["model"].items()))
                for name, row in [*report["kinds"].items(), ("total", report["total"])]:
                    print(f'{name} new_calls={row["new_calls"]} mean_prompt_tokens_est={row.get("mean_prompt_tokens_est", "-")} minutes={row["minutes_low"]}-{row["minutes_high"]}')
                return 0
            if not options.out:
                raise ConfigError("analyze --run: --out is required")
            source = project_path(options.run, "run", True)
            qa_dirs = [project_path(p, "qa", True) for p in options.qa]
            out = project_path(options.out, "out", False)
            boundary = (onprem.PROJECT_ROOT / "runs").resolve()
            for path in [source, *qa_dirs, out]:
                if not path.is_relative_to(boundary) or path == boundary:
                    raise ConfigError("analyze: directories must be strictly below runs/")
            for path in [source, *qa_dirs]:
                if not path.is_dir():
                    raise ConfigError(f"analyze: input must be a directory: {path}")
                if out.is_relative_to(path) or path.is_relative_to(out):
                    raise ConfigError("analyze: output must not overlap an input directory")
            report = analysis.analyze(source, qa_dirs)
            analysis.write(report, pipeline._output_dir(out, options.overwrite))
            for key in ("webnlg", "rejected", "judge", "qa", "alias"):
                print(f"Analyze {key}: {len(report[key] or {})} entries")
            print(f"Analyze exit 0: {out.relative_to(onprem.PROJECT_ROOT).as_posix()}/analysis.md")
            return 0
        if options.command == "ablate":
            from kgbuilder.core.config import load_ablation, load_qa, replay_files
            from kgbuilder.evaluation import ablation
            from kgbuilder.runtime import gateway as runtime_gateway
            from kgbuilder.serve import qa as qa_mod
            abl = load_ablation(Path(options.config))
            sets = ["llm.cache='off'" if s == "llm.cache=off" else s for s in options.sets]
            selected = pipeline.ablation_configs(abl, options.mock, sets, options.only, options.exclude)
            baselines = {name: {"label": b.label, "webnlg": evaluate.parse_eval_txt(b.eval_txt.read_text(encoding="utf-8"))}
                         for name, b in abl.baselines.items()}
            qa0 = None
            if abl.qa is not None and abl.qa.run in [cfg.run.name for cfg, _, _ in selected]:
                qa0 = load_qa(abl.qa.config, abl.qa.sets)
                if load_config(qa0.build_config, sets=sets, mock=options.mock).llm != selected[0][0].llm:
                    raise ConfigError("qa.build_config: selected run llm sections differ")
            out = project_path(options.out if options.out else onprem.PROJECT_ROOT / "runs" / abl.name, "out", False)
            boundary = (onprem.PROJECT_ROOT / "runs").resolve()
            if not out.is_relative_to(boundary) or out == boundary:
                raise ConfigError("out: must be a directory below runs/")
            if out.exists() and (not out.is_dir() or (any(out.iterdir()) and not options.overwrite)):
                raise ConfigError(f"out: directory is not empty: {out}; use --overwrite")
            for cfg, _, _ in selected:
                for message in pipeline.preflight(cfg):
                    print(message, file=sys.stderr)
            root = pipeline._output_dir(out, options.overwrite)
            first = selected[0][0]
            gateway = pipeline.open_gateway(first, root / first.run.name / selected[0][1][0] / "llm_calls.jsonl")
            qa_code, qa_levels = 0, []
            try:
                built = pipeline.ablate_builds(selected, root, gateway, core_log)
                if qa0 is not None:
                    qa_levels = [level for level in abl.qa.levels if built[abl.qa.run].get(level) is not None
                                 and built[abl.qa.run][level].exit_code == 0]
                    if qa_levels:
                        gateway.set_log(root / "qa/llm_calls.jsonl")
                        try:
                            graphs = {level: (root / abl.qa.run / level).relative_to(onprem.PROJECT_ROOT).as_posix() for level in qa_levels}
                            qa_cfg = load_qa(abl.qa.config, [*abl.qa.sets, "qa.graphs=" + json.dumps(graphs)])
                            try:
                                inputs = qa_mod.prepare(qa_cfg)
                                if first.llm.cache != "readonly":
                                    pipeline.model_ready(first)
                                qa_mod.eval_qa(qa_cfg, inputs, gateway.start(), first.llm.model, first.llm.profile,
                                               first.llm.timeout_s, gateway.set_stage, root / "qa")
                            except Exception:
                                pipeline.check_health(gateway, [core_log])
                                raise
                            pipeline.check_health(gateway, [core_log])
                        except KgbError as exc:
                            qa_code = exc.code
                            print(str(exc), file=sys.stderr)
                        finally:
                            pipeline._merge_net(root / "qa", [core_log])
            finally:
                gateway.stop()
            # Preserve CLI overrides for table flags and post-override run names, including skipped cells.
            resolved_abl = abl.model_copy(deep=True)
            for entry in resolved_abl.runs:
                entry.sets = [*entry.sets, *sets]
            runs = []
            for cfg, levels, excluded in selected:
                entry = next(e for e in resolved_abl.runs if load_config(e.config, sets=e.sets, mock=options.mock).run.name == cfg.run.name)
                runs.append(pipeline._summary_run(cfg, entry.config, entry.levels or abl.levels, built[cfg.run.name], abl.baselines))
            pipeline._write_summary(root, abl.name, abl.levels, options.mock, runs)
            paths = replay_files(first)
            if first.llm.cache != "off" and first.llm.cache_path.is_file():
                paths.append(first.llm.cache_path)
            index = runtime_gateway.load_replay(paths)[0]
            qa = ablation.qa_block(root / "qa", abl.qa.run, qa_levels, index) if qa_levels and not qa_code else None
            table = ablation.collect(resolved_abl, root, built, qa, index, options.mock, baselines, plan=first.llm.cache == "plan")
            ablation.write(table, root)
            if qa0 is not None and qa is None:
                report = root / "ablation.md"
                reason = f"exit {qa_code}" if qa_code else "no successful QA levels"
                report.write_text(report.read_text(encoding="utf-8").replace("QA: not run (no qa block)", f"QA: not run ({reason})"), encoding="utf-8", newline="\n")
            code = max([qa_code, *[r.exit_code for results in built.values() for r in results.values() if r is not None]])
            for row in table["rows"]:
                gold = row["showcase"] or row["webnlg"]
                print(f'{row["run"]} {row["level"]} {row["exit_code"]} {row["statements"]} {gold} {(row["llm"] or {}).get("new_calls")}')
            print(f"Ablation exit {code}: {root.relative_to(onprem.PROJECT_ROOT).as_posix()}/ablation.md")
            if code == 5 and options.mock:
                print("LLM replay miss: provide the recorded schema and judge fixtures, or --exclude the missing cells", file=sys.stderr)
            return code
        if options.command == "induce":
            from kgbuilder.build.refine import induce
            sets = ["llm.cache='off'" if s == "llm.cache=off" else s for s in options.sets]
            cfg = load_config(Path(options.config), sets=sets, mock=options.mock)
            source = project_path(options.run, "run", True)
            out = project_path(options.out, "out", False)
            boundary = (onprem.PROJECT_ROOT / "runs").resolve()
            if not source.is_relative_to(boundary) or source == boundary:
                raise ConfigError("run: must be a directory below runs/")
            if not out.is_relative_to(boundary) or out == boundary:
                raise ConfigError("out: must be a directory below runs/")
            if out.is_relative_to(source) or source.is_relative_to(out):
                raise ConfigError("out: must not overlap the source run")
            if out.exists() and (not out.is_dir() or (any(out.iterdir()) and not options.overwrite)):
                raise ConfigError(f"out: directory is not empty: {out}; use --overwrite")
            induce._inputs(source)
            for message in pipeline.preflight(cfg):
                print(message, file=sys.stderr)
            out = pipeline._output_dir(out, options.overwrite)
            gateway = pipeline.open_gateway(cfg, out / "llm_calls.jsonl")
            gateway.set_stage("induce.concepts")
            try:
                try:
                    summary = induce.induce(source, cfg, gateway.start(), out)
                except Exception:
                    pipeline.check_health(gateway, [core_log])
                    raise
                pipeline.check_health(gateway, [core_log])
            finally:
                gateway.stop()
                pipeline._merge_net(out, [core_log])
            rel = summary["relations"]
            print(f'relations {rel["open_types"]} -> {rel["canonical_types"]} -> {rel["induced_types"]}')
            print("redundancy " + " -> ".join(str(rel[k + "_redundancy"]) for k in ("open", "canonical", "induced")))
            print("coverage " + json.dumps(summary["coverage"], sort_keys=True))
            print("entity types " + json.dumps(sorted(summary["entity_types"].items(), key=lambda x: (-x[1], x[0]))[:5]))
            print(f'LLM calls {summary["llm"]["llm_calls"]}')
            print(f"Induce exit 0: {out.relative_to(onprem.PROJECT_ROOT).as_posix()}/schema_induced.yaml")
            return 0
        if options.command == "eval" and options.eval_mode == "qa":
            from kgbuilder.core.config import check_qa_out, load_qa
            from kgbuilder.serve import qa as qa_mod
            qa_cfg = load_qa(Path(options.config), [s for s in options.sets if s.startswith("qa.")])
            other_sets = [s for s in options.sets if not s.startswith("qa.")]
            # YAML 1.1 treats bare "off" as False; preserve the cache enum for this command.
            other_sets = ["llm.cache='off'" if s == "llm.cache=off" else s for s in other_sets]
            cfg = load_config(qa_cfg.build_config, sets=other_sets, mock=options.mock)
            out = Path(options.out) if options.out else onprem.PROJECT_ROOT / "runs" / qa_cfg.name
            out = project_path(out, "out", False)
            root = (onprem.PROJECT_ROOT / "runs").resolve()
            if not out.is_relative_to(root) or out == root:
                raise ConfigError("out: must be a directory below runs/")
            check_qa_out(out, qa_cfg)
            if out.exists() and (not out.is_dir() or any(out.iterdir())) and not options.overwrite:
                raise ConfigError(f"out: directory is not empty: {out}; use --overwrite")
            inputs = qa_mod.prepare(qa_cfg)
            for message in pipeline.preflight(cfg):
                print(message, file=sys.stderr)
            out_dir = pipeline._output_dir(out, options.overwrite)
            gateway = pipeline.open_gateway(cfg, out_dir / "llm_calls.jsonl")
            try:
                report = qa_mod.eval_qa(qa_cfg, inputs, gateway.start(), cfg.llm.model, cfg.llm.profile, cfg.llm.timeout_s, gateway.set_stage, out_dir)
                pipeline.check_health(gateway, [core_log])
            except Exception:
                pipeline.check_health(gateway, [core_log])
                raise
            finally:
                gateway.stop()
                pipeline._merge_net(out_dir, [core_log])
            for row in report["rows"]:
                print(f'{row["row"]} EM {row["em"]:.3f} F1 {row["f1"]:.3f} R@2 {row.get("recall@2", 0):.3f} R@5 {row.get("recall@5", 0):.3f} no_ctx {row["no_context"]} calls {row["llm"]["calls"]} seconds {row["wall_seconds"]:.3f}')
            for label, graph in report["graphs"].items():
                print(f'{label} entities {graph["entities"]} statements {graph["statements"]} er_reduction {((graph.get("build") or {}).get("er_reduction"))} evidence_pair_recall {graph["evidence_pair_recall"]}')
            print(f"QA exit 0: {out_dir.relative_to(onprem.PROJECT_ROOT).as_posix()}/qa.json")
            return 0
        if options.command == "preflight":
            cfg = load_config(Path(options.config), sets=options.sets)
            for message in pipeline.preflight(cfg, options.probe):
                print(message, file=sys.stderr if message.startswith("WARNING") else sys.stdout)
            pipeline.check_health(None, [core_log])
            print("Preflight OK")
            return 0
        if options.command == "build":
            cfg = load_config(Path(options.config), options.ablation, options.sets, options.mock)
            path = Path(options.out) if options.out else onprem.PROJECT_ROOT / "runs" / cfg.run.name / cfg.ablation
            # Validate containment and the overwrite boundary before any filesystem mutation.
            path = project_path(path, "out", False)
            root = (onprem.PROJECT_ROOT / "runs").resolve()
            if not path.is_relative_to(root) or path == root:
                raise ConfigError("out: must be a directory below runs/")
            if path.exists() and (not path.is_dir() or any(path.iterdir())) and not options.overwrite:
                raise ConfigError(f"out: directory is not empty: {path}; use --overwrite")
            for message in pipeline.preflight(cfg):
                print(message, file=sys.stderr)
            run_dir = pipeline._output_dir(path, options.overwrite)
            gateway = pipeline.open_gateway(cfg, run_dir / "llm_calls.jsonl")
            try:
                result = pipeline.build(cfg, run_dir, gateway, core_log)
                print(f"Build exit {result.exit_code}: {run_dir.relative_to(onprem.PROJECT_ROOT).as_posix()}")
                print("Gateway: " + json.dumps(gateway.stats, sort_keys=True))
                if result.exit_code == 5 and options.mock:
                    print("LLM replay miss: provide the recorded A5 judge and extraction fixtures"
                          if cfg.ablation == "A5" else replay_hint(cfg.llm.profile), file=sys.stderr)
                return result.exit_code
            finally:
                gateway.stop()
        if options.command == "run":
            demo = load_demo(Path(options.config))
            out = Path(options.out) if options.out else onprem.PROJECT_ROOT / "runs" / demo.name
            if options.overwrite:
                pipeline._demo_configs(demo, options.mock, options.sets, options.only)
                pipeline._output_dir(out, overwrite=True)
            code = pipeline.run_demo(demo, mock=options.mock, sets=options.sets, only=options.only,
                                     out_root=out, net_core_log=core_log)
            if code == 5 and options.mock:
                profile = pipeline._demo_configs(demo, True, options.sets, options.only)[0][1].llm.profile
                print(replay_hint(profile), file=sys.stderr)
            resolved_out = project_path(out, "out", False)
            summary = json.loads((resolved_out / "summary.json").read_text(encoding="utf-8"))
            print("run       level exit accepted gold")
            for run in summary["runs"]:
                for level in summary["levels"]:
                    value = run["levels"][level]
                    accepted = value["metrics"]["statements_accepted"] if value["metrics"] else "–"
                    gold = (value["showcase"]["gold_recall"] if value["showcase"] else
                            value["webnlg"]["strict"]["F1"] if value["webnlg"] else "–")
                    print(f'{run["name"]:<10}{level:<6}{value["exit_code"]:<5}{str(accepted):<9}{gold}')
            print(f"Demo exit {code}; report: {(resolved_out / 'report.html').relative_to(onprem.PROJECT_ROOT).as_posix()}")
            return code
        if options.command == "fixtures":
            count = pipeline.export_fixtures(Path(options.source), Path(options.target), options.overwrite)
            print(f"Exported {count} fixture rows")
            return 0
        if options.command == "neo4j" and options.neo4j_mode in ("domain-attach", "domain-audit"):
            from kgbuilder.core import domain
            from kgbuilder.core.config import neo4j_settings
            from kgbuilder.adapters.neo4j_domain import DomainStore
            settings = neo4j_settings(options.sets)
            password = os.environ.get("KGB_NEO4J_PASSWORD", "")
            if not password: raise ConfigError("KGB_NEO4J_PASSWORD is required")
            store = DomainStore(settings, password)
            try:
                result = (store.attach(domain.run_path(Path(options.run)) / "graph.json", domain.run_path(Path(options.links)))
                          if options.neo4j_mode == "domain-attach" else store.audit(domain.run_path(Path(options.tables)), domain.run_path(Path(options.bulk))))
                print(json.dumps(result, sort_keys=True))
            finally:
                store.close()
            return 0
        if options.command == "eval" and options.eval_mode == "attribution":
            from kgbuilder.core import domain, well_literals
            from kgbuilder.core.config import load_well_eval
            from kgbuilder.evaluation import well_gold
            from kgbuilder.evaluation.well_eval import verify_policy
            from kgbuilder.evaluation.well_attribution import attribute
            gold_cfg = well_gold.load_config(Path(options.gold_config))
            well_gold.verify(gold_cfg)
            policy_path = project_path(options.config, "evaluation config", True)
            verify_policy(policy_path, gold_cfg["root"])
            policy = load_well_eval(policy_path).model_dump()
            lexicon_path = project_path(options.lexicon, "lexicon", True)
            from kgbuilder.core.text import sha256_file
            freeze = domain.read_object(gold_cfg["root"] / "freeze.json")
            if (freeze.get("converter", "v1") == "v2"
                    and sha256_file(lexicon_path) != freeze["frozen_inputs"].get("configs/domains/bsee/bsee_literals.yaml")):
                raise ConfigError("converter lexicon hash differs from freeze")
            lexicon = well_literals.load_lexicon(lexicon_path)
            run, corpus = domain.run_path(Path(options.run)), domain.input_path(Path(options.corpus))
            out = domain.output_dir(Path(options.out), [run, corpus, gold_cfg["root"], policy_path, lexicon_path], options.overwrite)
            result = attribute(run, corpus, gold_cfg["root"], policy, lexicon, options.split, options.export, out)
            print(json.dumps({k: v for k, v in result.items() if k != "per_chunk"}, sort_keys=True))
            return 0
        if options.command == "eval" and options.eval_mode == "wells":
            from kgbuilder.core import domain
            from kgbuilder.core.config import load_well_eval
            from kgbuilder.evaluation.well_eval import evaluate_wells, verify_policy
            from kgbuilder.core.text import sha256_file
            if options.split == "dev" and not options.gold: raise ConfigError("--split dev requires --gold")
            if any((options.gold, options.labels, options.rules, options.baseline)) and not options.gold_config:
                raise ConfigError("--gold, --labels, --rules or --baseline requires --gold-config")
            cfg = load_well_eval(Path(options.config))
            policy_path = project_path(Path(options.config), "evaluation config", True)
            policy_hash = sha256_file(policy_path)
            run, corpus = domain.run_path(Path(options.run)), domain.input_path(Path(options.corpus))
            refs = {key: project_path(Path(getattr(options, key)), key, True) if getattr(options, key) else None
                    for key in ("labels", "rules", "gold", "baseline")}
            if options.gold_config:
                from kgbuilder.evaluation import well_gold
                gold_cfg = well_gold.load_config(Path(options.gold_config))
                if options.gold and refs["gold"] != gold_cfg["root"]: raise ConfigError("--gold differs from gold config root")
                well_gold.verify(gold_cfg)
                policy_hash = verify_policy(policy_path, gold_cfg["root"])
            out = domain.output_dir(Path(options.out), [run, corpus, *[p for p in refs.values() if p]], options.overwrite)
            print(json.dumps(evaluate_wells(run, corpus, cfg, out, **refs, policy_file_sha256=policy_hash, split=options.split), sort_keys=True))
            return 0
        if options.command == "fetch":
            from kgbuilder.core.config import load_bsee_sources
            from kgbuilder.build.ingest.bsee_sources import register_sources
            cfg = load_bsee_sources(Path(options.config))
            manifest = onprem.PROJECT_ROOT / ".cache/datasets/bsee" / cfg.snapshot / "manifest.json"
            result = register_sources(cfg, Path(options.from_dir), manifest)
            for name, entry in result["files"].items():
                print(f'{name} bytes={entry["bytes"]} sha256={entry["sha256"]}')
                for member, row in entry["members"].items():
                    print(f'  {member} bytes={row["bytes"]} encoding={row.get("encoding", "not mapped")}')
            print("positional_equality=" + json.dumps(result["positional_equality"], sort_keys=True))
            print("not_acquired=" + json.dumps(result["not_acquired"]))
            print("not_mapped=" + json.dumps(result["not_mapped"]))
            print("data_sha256=" + result["data_sha256"])
            return 0
        if options.command == "domain":
            from kgbuilder.core import domain
            if options.domain_mode == "corpus-v2":
                from kgbuilder.core.config import load_bsee_corpus_v2
                from kgbuilder.core.text import sha256_file
                from kgbuilder.build.ingest.bsee_corpus import select_gold_v2
                from kgbuilder.evaluation import well_gold
                cfg = load_bsee_corpus_v2(Path(options.config))
                gold_cfg = well_gold.load_config(cfg.exclude_gold_config)
                if "converter" in gold_cfg: raise ConfigError("excluded gold must use v1 converter")
                well_gold.verify(gold_cfg)
                frozen = domain.read_object(gold_cfg["root"] / "freeze.json")
                if sha256_file(cfg.source_corpus / "corpus.jsonl") != frozen["corpus_sha256"]:
                    raise ConfigError("corpus hash differs from freeze")
                split = domain.read_object(gold_cfg["root"] / "split.json")
                out = domain.output_dir(Path(options.out), [cfg.source_corpus, gold_cfg["root"], cfg.exclude_gold_config], options.overwrite)
                print(json.dumps(select_gold_v2(cfg.source_corpus, split["dev"] + split["test"], cfg, out), sort_keys=True))
                return 0
            if options.domain_mode == "split-corpus":
                from kgbuilder.build.ingest.bsee_corpus import split_subset
                from kgbuilder.core.text import sha256_file
                from kgbuilder.evaluation import well_gold
                cfg = well_gold.load_config(Path(options.gold_config))
                well_gold.verify(cfg)
                corpus = domain.input_path(Path(options.corpus))
                frozen = domain.read_object(cfg["root"] / "freeze.json")
                split_path = cfg["root"] / "split.json"
                split_hash = sha256_file(split_path)
                if split_hash != frozen["split_sha256"]: raise ConfigError("split hash differs from freeze")
                if sha256_file(corpus / "corpus.jsonl") != frozen["corpus_sha256"]:
                    raise ConfigError("corpus hash differs from freeze")
                ids = domain.read_object(split_path)["dev"]
                out = domain.output_dir(Path(options.out), [corpus, cfg["root"]], options.overwrite)
                print(json.dumps(split_subset(corpus, ids, options.part, split_hash, out), sort_keys=True))
                return 0
            if options.domain_mode == "bulk":
                from kgbuilder.build.publish.domain_export import export_bulk
                tables = domain.run_path(Path(options.tables))
                out = domain.output_dir(Path(options.out), [tables], options.overwrite)
                print(json.dumps(export_bulk(tables, out), sort_keys=True))
                return 0
            if options.domain_mode == "gold":
                from kgbuilder.evaluation import well_gold
                cfg = well_gold.load_config(Path(options.config))
                if options.gold_mode == "prepare":
                    result = well_gold.prepare(cfg, domain.input_path(Path(options.corpus)))
                elif options.gold_mode == "validate":
                    result = well_gold.validate(cfg, options.annotator, locations_only=options.locations_only)
                elif options.gold_mode == "seal":
                    result = well_gold.seal(cfg, options.annotator)
                elif options.gold_mode == "amend":
                    result = well_gold.amend(cfg, options.reason)
                elif options.gold_mode == "agreement":
                    out = domain.output_dir(Path(options.out), [cfg["root"]])
                    result = well_gold.agreement(cfg, out, domain.run_path(Path(options.rules)) if options.rules else None)
                else:
                    result = getattr(well_gold, options.gold_mode.replace("-", "_"))(cfg)
                print(json.dumps(result, sort_keys=True))
                if options.gold_mode == "verify":
                    print(json.dumps({"amendment_changes": well_gold._check_amendments(cfg)}, sort_keys=True))
                return 0
            if options.domain_mode == "rules":
                from collections import Counter
                from kgbuilder.core.text import iter_jsonl, sha256_file, write_json, write_jsonl
                from kgbuilder.evaluation.well_rules import RULES_VERSION, annotate
                from kgbuilder.evaluation import well_gold
                gold_cfg = well_gold.load_config(Path(options.gold_config))
                well_gold.verify(gold_cfg)
                frozen = domain.read_object(gold_cfg["root"] / "freeze.json")["frozen_inputs"]
                rule_file = "src/kgbuilder/evaluation/well_rules.py"
                if frozen.get(rule_file) != sha256_file(onprem.PROJECT_ROOT / rule_file): raise ConfigError("rules hash differs from freeze")
                corpus = domain.input_path(Path(options.corpus))
                out = domain.output_dir(Path(options.out), [corpus], options.overwrite)
                selected = {r["doc_id"] for r in iter_jsonl(corpus / "corpus.jsonl")}
                stats = {"ai_gold": Counter(), "eligible": Counter()}
                def rows():
                    for doc in iter_jsonl(corpus / "eligible.jsonl"):
                        facts = annotate(doc["doc_id"], doc["doc_id"] + "#c000", doc["text"])
                        yield {"record": "chunk", "format": "kgb.well_annotation/1", "annotator": RULES_VERSION, "chunk_id": doc["doc_id"] + "#c000",
                               "status": "annotated" if facts else "no_facts", "n_facts": len(facts), "note": ""}
                        for fact in facts:
                            stats["eligible"][fact.relation] += 1
                            if doc["doc_id"] in selected: stats["ai_gold"][fact.relation] += 1
                            row = fact.model_dump(exclude_none=True); row["time"] = fact.time
                            yield row
                write_jsonl(out / "rules.jsonl", rows())
                write_json(out / "rules_stats.json", stats)
                print(json.dumps(stats, sort_keys=True))
                return 0
            if options.domain_mode == "labels":
                from kgbuilder.core.config import load_well_eval
                from kgbuilder.evaluation.well_eval import make_silver, verify_policy
                from kgbuilder.evaluation import well_gold
                gold_cfg = well_gold.load_config(Path(options.gold_config))
                well_gold.verify(gold_cfg)
                cfg = load_well_eval(Path(options.config))
                verify_policy(project_path(Path(options.config), "evaluation config", True), gold_cfg["root"])
                tables, corpus = domain.run_path(Path(options.tables)), domain.input_path(Path(options.corpus))
                out = domain.output_dir(Path(options.out), [tables, corpus], options.overwrite)
                print(json.dumps(make_silver(tables, corpus, cfg, out), sort_keys=True))
                return 0
            if options.domain_mode == "link":
                import yaml
                from kgbuilder.build.refine.well_link import link_text
                run = domain.run_path(Path(options.run))
                tables = domain.run_path(Path(options.tables))
                sources = project_path(Path(options.sources), "sources", True)
                policy = yaml.safe_load(project_path(Path(options.policy), "policy", True).read_text(encoding="utf-8"))
                out = domain.output_dir(Path(options.out), [run, tables, sources], options.overwrite)
                print(json.dumps(link_text(run, tables, sources, policy, out), sort_keys=True))
                return 0
            if options.domain_mode == "corpus":
                from kgbuilder.core.config import load_bsee_corpus
                from kgbuilder.build.ingest.bsee_corpus import write_corpus
                cfg = load_bsee_corpus(Path(options.config))
                out = domain.output_dir(Path(options.out), [cfg.source_manifest, cfg.tables], options.overwrite)
                result = write_corpus(cfg, out)
                print(json.dumps(result, sort_keys=True))
                return 0
            if options.domain_mode == "tables":
                from kgbuilder.core.config import load_domain_tables
                from kgbuilder.build.ingest.bsee_tables import build_tables
                cfg = load_domain_tables(Path(options.config))
                out = domain.output_dir(Path(options.out), [cfg.source_manifest], options.overwrite)
                result = build_tables(cfg, out)
                print(json.dumps(result, sort_keys=True))
                print("historical_boreholes gom=55572 pacific=1714 alaska=167 (not asserted)")
                return 0
        run_dir = project_path(Path(options.run), "run", True)
        root = (onprem.PROJECT_ROOT / "runs").resolve()
        if not run_dir.is_relative_to(root) or run_dir == root:
            raise ConfigError("run: must be a directory below runs/")
        if options.command == "query":
            from kgbuilder.serve import query
            from kgbuilder.core.contracts import dump
            record = query.load_graph(run_dir)
            if options.query_mode == "alias":
                rows = [dump(e) for e in query.alias(record, options.text)]
            elif options.query_mode == "at":
                rows = query.at(record, options.subject, options.predicate, options.at)
            elif options.query_mode == "evidence":
                if options.statement is not None and (options.predicate is not None or options.object is not None):
                    raise ConfigError("evidence: use --statement or --subject/--predicate/--object")
                rows = query.evidence(record, options.statement, options.subject, options.predicate, options.object)
            else:
                rows = query.path(record, options.src, options.dst, options.max_hops)
            if options.json:
                print(json.dumps(rows, ensure_ascii=False, sort_keys=True))
            elif rows:
                for row in rows:
                    print(json.dumps(row, ensure_ascii=False, sort_keys=True))
            else:
                print("no path" if rows is None else "no result")
            return 0
        if options.command == "neo4j":
            from kgbuilder.core.config import neo4j_settings
            from kgbuilder.core.contracts import Mention
            from kgbuilder.core.text import read_jsonl, sha256_file
            from kgbuilder.serve import query
            from kgbuilder.adapters.neo4j_store import Neo4jGraphStore, demo_params
            settings = neo4j_settings(options.sets)
            password = os.environ.get("KGB_NEO4J_PASSWORD")
            if not password:
                raise ConfigError("KGB_NEO4J_PASSWORD is required (shell environment only)")
            record = query.load_graph(run_dir)
            mentions = []
            params = None
            if options.neo4j_mode == "load":
                source = run_dir / "mentions.jsonl"
                if source.is_file():
                    try:
                        mentions = [Mention.model_validate(row) for row in read_jsonl(source)]
                    except (ValueError, OSError) as exc:
                        raise ConfigError(f"mentions.jsonl: {exc}") from exc
            else:
                sid = options.statement
                if sid is None:
                    facts = query.at(record, options.subject, options.predicate, options.at)
                    sid = facts[0]["statement_id"] if facts else None
                params = demo_params(options.alias, options.subject, options.at, sid, options.src, options.dst)
            store = Neo4jGraphStore(settings.uri, settings.user, password, settings.database, settings.batch_size)
            try:
                store.verify()
                if options.neo4j_mode == "load":
                    result = store.load(record, mentions, sha256_file(run_dir / "graph.json"), options.wipe)
                    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
                else:
                    result = store.demo(options.predicate, params)
                    if options.json:
                        print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
                    else:
                        for name, rows in result.items():
                            if not rows:
                                print(f"{name}: no result")
                            for row in rows:
                                print(name + ": " + json.dumps(row, ensure_ascii=False, sort_keys=True, default=str))
                return 0
            finally:
                store.close()
        cfg = from_resolved(json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["config"])
        handler = pipeline._RunLog(run_dir / "run.log")
        handler.stage = "eval." + options.eval_mode
        logger.addHandler(handler)
        try:
            if options.eval_mode == "webnlg":
                if not cfg.canon.edc_python.is_file():
                    raise KgbError(3, f"missing EDC Python: {cfg.canon.edc_python}")
                scores = evaluate.eval_webnlg(run_dir, cfg)
            else:
                scores = evaluate.eval_showcase(run_dir, cfg)
            pipeline.check_health(None, [core_log, run_dir / "eval/net_eval.jsonl"])
            print(json.dumps(scores, ensure_ascii=False, sort_keys=True))
        except Exception:
            pipeline.check_health(None, [core_log, run_dir / "eval/net_eval.jsonl"])
            logger.exception("evaluation failed")
            raise
        finally:
            pipeline._merge_net(run_dir, [core_log, run_dir / "eval/net_eval.jsonl"])
            logger.removeHandler(handler)
            handler.close()
        return 0
    except KgbError as exc:
        print(str(exc), file=sys.stderr)
        if exc.code == 5 and options.command == "induce" and options.mock:
            print("LLM replay miss: provide the recorded schema induction fixture", file=sys.stderr)
        if exc.code == 5 and options.command == "eval" and options.eval_mode == "qa" and options.mock:
            print("LLM replay miss: provide the recorded QA fixture", file=sys.stderr)
        return exc.code
    except Exception as exc:
        if (options.command == "domain" or options.command == "fetch"
                or options.command == "eval" and options.eval_mode in {"wells", "attribution"}
                or options.command == "neo4j" and options.neo4j_mode in ("domain-audit", "domain-attach")):
            print(f"domain input/operation failed ({type(exc).__name__}); no row contents logged", file=sys.stderr)
            return 2
        if run_dir is not None and run_dir.is_dir():
            with (run_dir / "run.log").open("a", encoding="utf-8", newline="\n") as stream:
                from kgbuilder.core.text import cj
                stream.write(cj({"level": "ERROR", "msg": str(exc), "traceback": traceback.format_exc()}) + "\n")
        print(traceback.format_exc(), file=sys.stderr)
        return 1
    finally:
        logger.removeHandler(stdout)
        logger.removeHandler(stderr)
