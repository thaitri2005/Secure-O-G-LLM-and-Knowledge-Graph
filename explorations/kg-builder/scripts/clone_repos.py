"""Create or verify upstream clones against the immutable repository lock."""
import argparse
import csv
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    result = subprocess.run(['git', *args], capture_output=True, text=True,
                            env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'})
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def run(verify_only=False):
    lock = ROOT / 'configs/runtime/repos.lock.csv'
    original = lock.read_bytes()
    rows = list(csv.DictReader(original.decode('utf-8-sig').splitlines()))
    for row in rows:
        name, url, commit = row['name'], row['url'], row['sha']
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', name) or not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise ValueError('Invalid pinned repository identity')
        if not url.startswith('https://github.com/') or row['status'] != 'ok':
            raise ValueError('Invalid pinned repository source')
        path = ROOT / 'third_party' / name
        if not path.exists():
            if verify_only:
                raise RuntimeError(f'Missing pinned clone: {name}')
            path.parent.mkdir(exist_ok=True)
            git('clone', '--no-checkout', url, str(path))
            git('-C', str(path), 'checkout', '--detach', commit)
        head = git('-C', str(path), 'rev-parse', 'HEAD')
        status = git('-C', str(path), 'status', '--porcelain', '--ignored')
        if head != commit or status:
            raise RuntimeError(f'Pinned clone mismatch or dirty tree: {name}')
        print(f'{name}: {head} clean', flush=True)
    if lock.read_bytes() != original:
        raise RuntimeError('Repository lock changed')
    return len(rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    run(args.verify_only)
