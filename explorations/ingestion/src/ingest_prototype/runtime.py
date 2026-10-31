"""Resolve repository resources and keep all generated artifacts local."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

BASE = Path(__file__).resolve().parents[2]
ROOT = BASE.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'src'))
for variable, directory in {
    'HF_HOME': '.cache/huggingface', 'TORCH_HOME': '.cache/torch',
    'XDG_CACHE_HOME': '.cache', 'TEMP': '.cache/tmp', 'TMP': '.cache/tmp',
}.items():
    os.environ[variable] = str(BASE / directory)
os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                  DO_NOT_TRACK='1', PYTHONDONTWRITEBYTECODE='1')


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n'
                            for row in rows), encoding='utf-8')


def canonical(value: Any, geometry: bool = False) -> Any:
    if isinstance(value, dict):
        return {key: canonical(item, geometry or key in {'bbox', 'key_bbox', 'value_bbox', 'width', 'height'})
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(item, geometry) for item in value]
    if isinstance(value, float) and geometry:
        return round(value, 2) or 0.0
    return value
