"""Verify source PDFs and cached model bytes without network access."""
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE / 'src'))
from ingest_prototype.runtime import ROOT, digest, read


def main() -> None:
    lock = read(BASE / 'configs/inputs.lock.json')
    for asset in lock['runtime']['assets']:
        if digest(BASE / asset['path']) != asset['sha256']:
            raise ValueError('Model asset differs: ' + asset['path'])
    for asset in lock['native_files']:
        if digest(BASE / asset['path']) != asset['sha256']:
            raise ValueError('Native asset differs: ' + asset['path'])
    comparison = lock['comparison_model']
    if digest(BASE / comparison['path']) != comparison['sha256']:
        raise ValueError('Comparison model differs from its pin')
    for source in lock['source_pdfs']:
        if digest(ROOT / source['path']) != source['sha256']:
            raise ValueError('Source PDF differs: ' + source['path'])
    print('Source PDF and parser-asset hashes match.')


if __name__ == '__main__':
    main()
