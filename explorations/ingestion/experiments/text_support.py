"""Replay support thresholds from frozen page and span measurements."""
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'src'))
from ingest_prototype.runtime import read


def evaluate() -> list[dict]:
    measurements = read(BASE / 'results/text-support/scores.json')
    correct = [row for row in measurements['records'] if row['cohort']]
    results = []
    for threshold in (.90, .95, .98):
        for rule in ('strict_zero', 'long_zero', 'low_support'):
            flags = sum(row['supported_share'] < threshold or bool(row['span_effects'][rule]) for row in correct)
            results.append(dict(threshold=threshold, span_rule=rule, false_flags=flags, correct_pages=len(correct)))
    return results


if __name__ == '__main__':
    print(evaluate())
