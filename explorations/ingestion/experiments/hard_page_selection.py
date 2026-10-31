"""Replay pre-registered selection formulas over the retained corpus signals."""
import csv
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'src'))
from ingest_prototype.runtime import read


def rules(row: dict) -> dict[str, bool]:
    rotated = int(row['rotation']) != 0
    landscape = row['landscape'] == 'True'
    ocr = row['mode'] == 'ocr'
    area = float(row['largest_table_share'] or 0)
    empty = int(row['empty_columns'] or 0)
    forms = int(row['form_pairs'] or 0)
    score = float(row['table_score']) if row['table_score'] else None
    return {
        'broad': rotated or landscape or ocr or area >= .60 or empty >= 3 or (score is not None and score < .50) or forms >= 8,
        'moderate': rotated or ocr or (landscape and forms >= 4) or area >= .80 or empty >= 5 or (score is not None and score < .35) or forms >= 12,
        'constrained': rotated or (ocr and forms >= 4) or (forms >= 8 and area >= .35) or (empty >= 3 and area >= .50) or (score is not None and score < .20),
    }


def evaluate() -> list[dict]:
    with (BASE / 'results/hard-page-selection/signals.csv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    required = {(row['doc_id'], row['page']) for row in read(BASE / 'results/hard-page-selection/scores.json')['required']}
    results = []
    for rule in ('broad', 'moderate', 'constrained'):
        selected = {(row['doc_id'], int(row['page'])) for row in rows if rules(row)[rule]}
        results.append(dict(rule=rule, selected=len(selected), pages=len(rows), caught=len(selected & required),
                            required=len(required), passed=required <= selected and len(selected) / len(rows) <= .15))
    return results


if __name__ == '__main__':
    print(evaluate())
