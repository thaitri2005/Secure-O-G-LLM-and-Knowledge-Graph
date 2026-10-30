"""Compatibility shim: the new guard truncates a log the first time a process opens it (the old shim appended), so never re-run a minitest against an existing log name; use new --out names."""
from __future__ import annotations
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from kgbuilder.runtime.onprem import PROJECT_ROOT, LOCAL_HOSTS, load_env, require_loopback_url
from kgbuilder.runtime.onprem import guard_network as _guard_network

load_env()


def guard_network(log_name: str) -> Path:
    return _guard_network(PROJECT_ROOT / "runs/upstream/logs" / f"{log_name}.jsonl")


def local_endpoint() -> tuple[str, str]:
    base_url = os.environ["LMSTUDIO_BASE_URL"]
    try:
        require_loopback_url(base_url, "LMSTUDIO_BASE_URL", ("http", "https"))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return base_url, os.environ["LMSTUDIO_API_KEY"]
