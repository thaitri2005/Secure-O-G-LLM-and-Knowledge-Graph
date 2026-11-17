"""A-445: how many pages does each fidelity severity policy flag (WARN/ERROR)? Read-only on releases, corpora and PDFs.

Three policies are compared on the same pages and the same PDF readings:
  B2   config without the block_*/enumerators keys (the A-416 behaviour; list numbers count as lost numbers in the recall)
  B3   current config with enumerators.marker_severity = INFO (the B3 downgrade)
  B4   current config as shipped (marker_severity = WARN)
For every page whose flag state differs between policies the row lists the codes, so that a 'cleared' page can be traced and viewed.
The tool counts flags. It does not say whether a flag is right: that needs the viewed crops (A-445 results).
Usage (repo root, PYTHONPATH=src):
  python scripts/qa_severity_policy_eval.py --set NAME=RELEASE_DIR,CORPUS_DIR [--set ...] --out OUT.json
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

from graph_builder.corpus.qa import fidelity as fid

BAD = ("WARN", "ERROR")


def policies(config_path: Path) -> dict[str, dict]:
    current = fid.load_config(config_path)
    b2 = copy.deepcopy(current)
    for key in ("block_edge_lines", "block_min_pages", "block_frequency"):
        b2["furniture"].pop(key, None)
    b2.pop("enumerators", None)
    b3 = copy.deepcopy(current)
    b3.setdefault("enumerators", {}).setdefault("marker_severity", {})["value"] = "INFO"
    return {"B2": b2, "B3": b3, "B4": current}


def flagged_codes(raw: dict, mode: str, k1_empty: bool, config: dict) -> list[str]:
    severity = {code: sev for code, sev, _, _ in fid.REASONS}
    severity[fid.MARKER_CODE] = fid.marker_severity(config)
    return sorted(code for code, _ in fid.judge(raw, mode, k1_empty, config) if severity[code] in BAD)


def evaluate(release: Path, corpus: Path, configs: dict[str, dict]) -> dict:
    states = {name: fid.FidelityState(release, corpus, config) for name, config in configs.items()}
    pages = sorted(((row["file_id"], row["page"], row.get("mode") or row.get("conversion_mode")) for row in fid.iter_jsonl(release / "pages.jsonl")),
                   key=lambda item: (item[0], item[1]))
    counts = {name: 0 for name in configs}
    compared, rows = 0, []
    for file_id, page, mode in pages:
        if mode == "ocr":
            continue
        try:
            codes = {}
            for name, state in states.items():
                raw, _ = state.analyse(file_id, page)
                if raw is None:
                    codes = None
                    break
                codes[name] = flagged_codes(raw, str(mode), state.k1_text(file_id, page).strip() == "", configs[name])
        except Exception as error:  # noqa: BLE001 - one broken page must not lose the others
            rows.append({"file_id": file_id, "page": page, "error": type(error).__name__})
            continue
        if codes is None:
            continue
        compared += 1
        for name in configs:
            counts[name] += bool(codes[name])
        if len({bool(value) for value in codes.values()}) > 1 or fid.MARKER_CODE in codes["B4"]:
            rows.append({"doc_id": states["B4"].files[file_id]["doc_id"], "file_id": file_id, "page": page, "mode": mode, "codes": codes})
    for state in states.values():
        state.close()
    return {"pages_compared": compared, "pages_flagged": counts, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", action="append", required=True, metavar="NAME=RELEASE,CORPUS")
    parser.add_argument("--config", type=Path, default=Path("configs/qa/source_fidelity.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    configs = policies(args.config)
    report: dict = {"config_sha256": fid.sha256_file(args.config), "sets": {}}
    for item in args.set:
        name, rest = item.split("=", 1)
        release, corpus = rest.split(",")
        report["sets"][name] = evaluate(Path(release), Path(corpus), configs)
        print(name, report["sets"][name]["pages_compared"], report["sets"][name]["pages_flagged"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
