"""Materialize shipped evaluation records in disposable reference run trees."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


def prepare(root: Path) -> int:
    root = root.resolve()
    entries = json.loads((root / 'data/evaluation/reference_files.json').read_text(encoding='utf-8'))
    count = 0
    for entry in entries:
        source = (root / entry['source']).resolve()
        target = (root / entry['destination']).resolve()
        if not source.is_relative_to(root) or not target.is_relative_to(root / 'runs/reference'):
            continue
        if not source.is_file():
            raise ValueError(f'Missing reference input: {entry["source"]}')
        if not target.is_file() or hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            count += 1
    return count


if __name__ == '__main__':
    print(f'Reference files refreshed: {prepare(Path(__file__).resolve().parents[1])}')
