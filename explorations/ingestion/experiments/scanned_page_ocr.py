"""Display completed scanned page ocr evaluation using the shared scorer."""
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'src'))
from ingest_prototype.evaluate import evaluate


if __name__ == '__main__':
    result = evaluate([BASE / 'runs/prototype/ak3', BASE / 'runs/prototype/reports'])
    print(result['scanned_pages'])
