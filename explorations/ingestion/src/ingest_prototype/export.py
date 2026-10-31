"""Serialize canonical bundles; run measurements remain outside their checksums."""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil

from .runtime import canonical, digest, jsonl, read, records, write

GROUPS = ('files', 'pages', 'tables', 'forms', 'parents', 'chunks')


def publish(run: Path, directories: list[Path], identity: str, config: dict) -> Path:
    from .validate import validate
    target = run / 'bundle'
    pending = run / 'bundle-pending'
    from .runtime import BASE
    for directory in (run, target, pending):
        if not directory.resolve().is_relative_to((BASE / 'runs').resolve()):
            raise ValueError('Publication directory escaped the local runs directory')
    if pending.exists():
        shutil.rmtree(pending)
    pending.mkdir()
    sets = {name: [] for name in GROUPS}
    for directory in directories:
        for name in GROUPS:
            sets[name].extend(records(directory / (name + '.jsonl')))
        for source in (directory / 'text').glob('*.txt'):
            destination = pending / 'text' / source.name
            destination.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, destination)
    for name, rows in sets.items():
        jsonl(pending / (name + '.jsonl'), [canonical(row) for row in rows])
    write(pending / 'manifest.json', {'format': 'K1', 'identity': identity, 'config': config,
        'counts': {name: len(rows) for name, rows in sets.items()}, 'geometry_pdf_points': 0.01,
        'timing': 'external measurements only', 'second_opinion': False})
    paths = sorted(p for p in pending.rglob('*') if p.is_file())
    (pending / 'SHA256SUMS').write_text(''.join(f'{digest(p)}  {p.relative_to(pending).as_posix()}\n' for p in paths), encoding='utf-8')
    check = validate(pending)
    write(run / 'checks.json', check)
    if check['errors']:
        raise ValueError(check['errors'][:10])
    if target.exists():
        shutil.rmtree(target)
    pending.replace(target)
    return target
