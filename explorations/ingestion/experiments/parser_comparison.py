"""Recompute grid comparison from retained native anchor snapshots."""
from pathlib import Path
import statistics
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'src'))
from ingest_prototype.runtime import ROOT, read
from ingest_prototype.evaluate import csv_rows
from graph_builder.ingestion.scoring import cell_grid, match_table, score_grid


def evaluate() -> dict:
    rows = []
    gold = read(ROOT / 'data/gold/ingestion/tables.json')
    for path in sorted((BASE / 'results/parser-comparison/native').glob('*.json')):
        native = read(path)
        for annotation in gold:
            if annotation['format'] != 'grid' or (annotation['doc_id'], annotation['page']) != (native['doc_id'], native['page']):
                continue
            table, overlap = match_table(annotation, native['tables'])
            expected = csv_rows(ROOT / annotation['csv'])
            rows.append(dict(method=native['variant'], id=annotation['id'],
                             **score_grid(expected, cell_grid(table) if table else [], annotation['header_rows'])))
    means = {method: statistics.mean(row['cell_accuracy'] for row in rows if row['method'] == method)
             for method in sorted({row['method'] for row in rows})}
    return {'tables': rows, 'mean_cell_accuracy': means,
            'keep_fast': means['corpus_fast'] >= means['vlm_mineru'] - .05,
            'large_vlm_wins': [row['id'] for row in rows if row['method'] == 'vlm_mineru' and
                              row['cell_accuracy'] - next(r['cell_accuracy'] for r in rows if r['method'] == 'corpus_fast' and r['id'] == row['id']) >= .10]}


if __name__ == '__main__':
    print(evaluate())
