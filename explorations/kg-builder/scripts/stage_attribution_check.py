"""Cross-check attribution TP counts against frozen DEV/TEST scoring."""
import argparse
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('attribution', type=Path)
parser.add_argument('evaluation', type=Path)
parser.add_argument('export', choices=('full', 'strict'))
args = parser.parse_args()
with (args.attribution / 'attribution.json').open(encoding='utf-8') as stream:
    attribution = json.load(stream)['scores']
with (args.evaluation / 'scores.json').open(encoding='utf-8') as stream:
    scores = json.load(stream)['exports'][args.export]['ai_gold']
equal = True
for level in ('L1', 'L2', 'L3'):
    left, right = attribution[level]['tp'], scores[level]['tp']
    match = left == right
    equal &= match
    print('%s %s attribution_tp=%s eval_tp=%s %s' % (args.export, level, left, right, 'PASS' if match else 'FAIL'))
sys.exit(0 if equal else 1)
