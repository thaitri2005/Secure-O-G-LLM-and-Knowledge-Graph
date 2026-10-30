"""Verify offline prerequisites without downloading assets or invoking a model."""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from clone_repos import run as verify_clones

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-local', action='store_true')
    parser.add_argument('--wheels', type=Path)
    args = parser.parse_args()
    verify_clones(True)
    if args.install_local:
        if not args.wheels or not args.wheels.is_dir():
            raise ValueError('An existing offline wheel directory is required')
        (ROOT / '.cache/tmp').mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp', prefix='install-') as temp:
            source = Path(temp) / 'source'
            shutil.copytree(ROOT / 'third_party/kg-gen', source, ignore=shutil.ignore_patterns('.git'))
            subprocess.run([str(ROOT / '.venvs/kggen/Scripts/python.exe'), '-m', 'pip', 'install',
                            '--no-index', '--find-links', str(args.wheels), '--no-deps', str(source)], check=True)
        return
    for name, version, imports in [('kggen', (3, 12), 'import kg_gen, yaml, pydantic, dspy, sentence_transformers, neo4j'),
                                    ('edc', (3, 9), 'import torch, sentence_transformers, pandas, openai'),
                                    ('gliner', (3, 12), 'import gliner')]:
        python = ROOT / '.venvs' / name / 'Scripts/python.exe'
        code = f'import sys; assert sys.version_info[:2] == {version!r}; {imports}; print("{name}: imports OK")'
        subprocess.run([str(python), '-B', '-c', code], cwd=ROOT, check=True)
        subprocess.run([str(python), '-B', str(ROOT / 'scripts/verify_requirements.py'),
                        str(ROOT / 'configs/requirements' / (name + '.txt'))], cwd=ROOT, check=True)
    assets = json.loads((ROOT / 'configs/runtime/assets.json').read_bytes())
    for name, asset in assets['models'].items():
        path = ROOT / asset['path']
        if not path.is_dir() or not (path / 'config.json').is_file() or asset['revision'] not in path.parts:
            raise RuntimeError(f'Missing pinned embedding snapshot: {name}')
        print(f'{name}: {asset["revision"]} present')
    for name in assets['nltk']:
        base = ROOT / '.cache/nltk/tokenizers'
        if not (base / name).exists() and not (base / (name + '.zip')).exists():
            raise RuntimeError(f'Missing NLTK asset: {name}')
    print('Offline prerequisites verified; no downloads or inference performed')


if __name__ == '__main__':
    main()
