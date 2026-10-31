"""Extract checksum-pinned Windows OCR binaries without executing installers."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

BASE = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    lock = json.loads((BASE / 'configs/inputs.lock.json').read_text())['native']
    for asset in lock['assets']:
        path = BASE / asset['path']
        if args.dry_run:
            print(f"GET {asset['url']} -> {path.as_posix()} sha256={asset['sha256']}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != asset['sha256']:
            with urllib.request.urlopen(asset['url'], timeout=120) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != asset['sha256']:
                raise ValueError('Native asset checksum mismatch')
            path.write_bytes(data)
    native = BASE / '.cache/native'
    commands = [
        [str(native / '7zr.exe'), 'x', str(native / '7z2605-x64.exe'), '-o' + str(native / '7zip'), '-y'],
        [str(native / '7zip/7z.exe'), 'x', str(native / 'tesseract-ocr-w64-setup-5.4.0.20240606.exe'),
         '-o' + str(BASE / '.cache/tesseract'), '-y'],
        [str(BASE / '.cache/tesseract/tesseract.exe'), '--version'],
    ]
    for command in commands:
        if args.dry_run:
            print(' '.join(command))
        else:
            # 7-Zip can return 1 for the PE header warning; extraction must still yield Tesseract.
            result = subprocess.run(command, check=False)
            if result.returncode not in (0, 1):
                raise RuntimeError('Native extraction failed')
    if not args.dry_run and not (BASE / '.cache/tesseract/tessdata/eng.traineddata').is_file():
        raise RuntimeError('English OCR data missing')


if __name__ == '__main__':
    main()
