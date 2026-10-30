# Usage

Run commands from the repository root in Windows PowerShell. Paths in committed configuration are relative to that root. The runner loads `configs/runtime/onprem.env`; `.env.example` documents variable names and is not loaded. Loopback API key placeholders are dummy values. Supply a Neo4j password only in the shell environment.

## Prerequisites and setup

The main environment uses Python 3.12; EDC uses Python 3.9 and its separate requirements. The optional entity-recognition environment has its own lock. Exact package versions live in `configs/requirements/`; repository commits are in `configs/runtime/repos.lock.csv`. The top-level `requirements.txt` describes direct imports, not the complete environment.

Provide offline wheels and the two pinned embedding snapshots listed in `configs/runtime/assets.json`, plus NLTK `punkt` and `punkt_tab`. Local environments and assets are ignored. Setup verifies existing prerequisites with `scripts/setup.ps1 -VerifyOnly`; an offline installation uses its wheel-directory option. Pinned upstream cloning is separate from package installation and never changes the lock file. No setup command performs LLM inference.

```powershell
.\scripts\setup.ps1 -Clone -Python312 python3.12
.\scripts\setup.ps1 -WheelDir ..\offline-wheels -Python312 python3.12 -Python39 python3.9
.\scripts\setup.ps1 -VerifyOnly
```

Use executable paths if those Python commands are unavailable. Cloning requires network access; installation uses only the supplied wheels. Populate the ignored asset paths from `configs/runtime/assets.json` before verification. Verification checks all three environments, their requirement pins, upstream commits and local assets; it does not install missing prerequisites. Keep the wheel directory outside the published tree.

## Recorded runs and reproduction

```powershell
.\scripts\reproduce.ps1 --quick
.\scripts\reproduce.ps1 --full --workers 2
.\kgb.ps1 run --config configs/experiments/demo.yaml --mock
.\kgb.ps1 build --config configs/experiments/bsee_text_test_v2_guided.yaml --mock --out runs/local_guided
```

Quick reproduction has a five-minute planning budget; full reproduction has a 1,800-second planning budget and is typically ~25 min on a laptop CPU with 2 workers. These are soft budgets: exceeding one prints a WARNING and does not fail correctness checks. Both modes have a 5,400-second hard safety limit. Wall time and both limits are recorded in the run report. Two workers are the default; more workers can be slower on a CPU laptop. Run on an otherwise idle machine; reproduction holds a sleep inhibitor while it runs.

Quick scores shipped inputs; full adds fresh recorded-response builds, all additional replay groups and graph comparisons. Correctness requires all groups to complete with zero cache misses and zero differences. Missing fixtures, mismatches and incomplete runs fail; exceeding the planning budget alone does not. Optional raw-table construction is outside those defaults. The expected-results ledger is immutable.

Use `--out` for a new generated directory. Existing outputs require explicit `--overwrite`. Generated files must stay inside the project and must not overlap input directories. `--set key=value` overrides a configuration field; an override creates a different experiment and may invalidate recorded request keys. Do not edit prompt text or response fixtures to make a replay pass.

## Live use

Start the configured model in LM Studio with its server bound to loopback, then run:

```powershell
.\kgb.ps1 preflight --config configs/experiments/webnlg10.yaml
.\kgb.ps1 run --config configs/experiments/demo.yaml
```

`--probe` explicitly requests a model probe; ordinary preflight checks configuration and runtime availability. Live calls are not part of offline reproduction. Model, prompt or token-setting changes can produce different outputs. Remote-service profiles require explicit configuration; they are not evidence for the published local results.

## Evaluation and gold verification

```powershell
.\kgb.ps1 eval qa --config configs/experiments/twowiki10_qa.yaml --mock
.\kgb.ps1 domain gold verify --config configs/experiments/bsee_gold.yaml
.\kgb.ps1 domain gold verify --config configs/experiments/bsee_gold_v2.yaml
.\kgb.ps1 test
```

The runner materializes required small reference inputs before tests. Gold validation and sealing use `--annotator annotator_a`, `annotator_b` or `adjudicator`. Existing published gold is already sealed: verify it rather than recreating or editing annotations. Use synthetic fixtures for tooling changes.

Public CLI names describe operations: `build`, `run`, `induce`, `ablate`, `analyze`, `eval qa`, `eval wells`, `eval attribution`, `domain tables`, `domain corpus`, `domain corpus-v2` and `domain gold`. Publication changes renamed paths and roles; they did not add a new inference command. The stage-attribution utility is `scripts/stage_attribution_check.py`.

## Optional BSEE table construction and Neo4j

Supply the required public BSEE downloads locally, with the schema and manifest expected by the dataset configuration. Raw downloads are not bundled. The fetch command imports from an existing local directory:

```powershell
.\kgb.ps1 domain tables --config configs/experiments/bsee_tables.yaml --out runs/bsee_tables
.\kgb.ps1 domain tables --config configs/experiments/bsee_tables_extended.yaml --out runs/bsee_tables_extended
```

The configurations expect `.cache/datasets/bsee/bsee_public_snapshot/manifest.json`. A new source import requires a source configuration for `fetch bsee --config <source-config> --from-dir <local-download-directory>`; raw-source acquisition is not included. Recorded construction times were about two to three minutes per bundle on the original machine, with substantially larger disk outputs than this repository. This path makes no LLM calls. Inspect the required source tables before use.

Neo4j import is optional. `scripts/bsee_neo4j_import.ps1` documents its parameters and rejects a nonempty target store before invoking Docker. Never point it at a database containing data you want to keep. JSON remains the source of truth; neither reproduction nor the normal test suite needs a running Neo4j service.

## Packaging

```powershell
.\scripts\package.ps1 -OutDir dist
```

Packages include implementation, tests, recorded fixtures, benchmarks and published results. They exclude local environments, caches, dependencies, generated outputs, raw database stores and secret environment files. Review [NOTICE](../NOTICE.md) before redistribution; the project licence is not yet assigned.
