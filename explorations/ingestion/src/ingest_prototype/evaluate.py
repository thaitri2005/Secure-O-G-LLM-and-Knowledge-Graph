"""Score all frozen annotations using completed local conversion bundles."""
from __future__ import annotations

from collections import Counter
import csv
import gzip
from pathlib import Path

from .runtime import BASE, ROOT, digest, read, records, write


def whitespace(text: str) -> str:
    return ' '.join(text.split())


def normalize_quotes(text: str) -> str:
    return text.translate(str.maketrans({'’': "'", '‘': "'", '′': "'", '”': '"', '“': '"', '″': '"'}))


def distance(left, right) -> int:
    try:
        from rapidfuzz.distance import Levenshtein
        return Levenshtein.distance(left, right)
    except ImportError:
        previous = list(range(len(right) + 1))
        for i, a in enumerate(left, 1):
            current = [i]
            for j, b in enumerate(right, 1):
                current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
            previous = current
        return previous[-1]


def transcription(expected: str, actual: str, critical: list[str], quotes: bool = False) -> dict:
    convert = normalize_quotes if quotes else lambda text: text
    a, b = whitespace(convert(expected)), whitespace(convert(actual))
    tokens = [whitespace(convert(token)) for token in critical]
    source, predicted = Counter(a.split()), Counter(b.split())
    character_edits, word_edits = distance(a, b), distance(a.split(), b.split())
    return {'critical_matches': sum(token in b for token in tokens), 'critical_count': len(tokens),
            'missed_critical_tokens': [token for token, normalized in zip(critical, tokens) if normalized not in b],
            'character_edits': character_edits, 'reference_characters': len(a),
            'CER': character_edits / len(a) if a else None,
            'word_edits': word_edits, 'reference_words': len(a.split()),
            'WER': word_edits / len(a.split()) if a else None,
            'word_recall_matches': sum((source & predicted).values()),
            'word_recall': sum((source & predicted).values()) / sum(source.values()) if source else None}


def pair_score(expected: list, actual: list, reference: str) -> dict:
    gold = Counter((whitespace(key), whitespace(value)) for key, value in expected)
    pred = Counter((whitespace(field['key']), whitespace(field['value'])) for field in actual)
    matched, union = sum((gold & pred).values()), sum((gold | pred).values())
    invented = [field['value'] for field in actual if whitespace(field['value']) and whitespace(field['value']) not in whitespace(reference)]
    boxes = sum(bool(field.get('key_bbox')) and (not field['value'] or bool(field.get('value_bbox'))) for field in actual)
    return dict(matched=matched, gold_pairs=sum(gold.values()), predicted_pairs=sum(pred.values()),
                pair_accuracy=matched / union if union else None,
                pair_recall=matched / sum(gold.values()) if gold else None,
                pair_precision=matched / sum(pred.values()) if pred else None,
                literal_source_absent_values=invented, literal_source_absent_count=len(invented),
                bbox_pairs=boxes, bbox_share=boxes / len(actual) if actual else None,
                errors=[dict(key=key, value=value, missing=count) for (key, value), count in (gold - pred).items()])


def annotated_box_coverage(expected: list[dict], actual: list[dict]) -> dict:
    """Match duplicate pairs spatially and measure reviewed key/value box overlap."""
    from graph_builder.ingestion.scoring import bbox_iou
    remaining = list(actual)
    overlaps = []
    for field in expected:
        candidates = [p for p in remaining if (whitespace(p['key']), whitespace(p['value'])) ==
                      (whitespace(field['key']), whitespace(field['value']))]
        selected = max(candidates, key=lambda p: bbox_iou(p['key_bbox'], field['key_bbox']), default=None)
        if selected:
            remaining.remove(selected)
        for key in ('key_bbox', 'value_bbox'):
            if field.get(key):
                overlaps.append(bbox_iou(field[key], selected[key]) if selected and selected.get(key) else 0.0)
    return {'annotated_boxes': len(overlaps), 'boxes_with_positive_overlap': sum(value > 0 for value in overlaps),
            'annotated_bbox_coverage': sum(value > 0 for value in overlaps) / len(overlaps) if overlaps else None,
            'mean_matched_bbox_iou': sum(overlaps) / len(overlaps) if overlaps else None}


def annotation_path(old: str) -> Path:
    if old.startswith('data/'):
        return ROOT / old
    relocation = BASE / 'configs/annotation-paths.json'
    mapped = read(relocation)['paths'].get(old, old) if relocation.exists() else old
    return BASE / mapped


def csv_rows(path: Path) -> list[list[str]]:
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.reader(stream))


def grid_errors(expected: list, predicted: list, limit: int = 3) -> list:
    errors = []
    for row, values in enumerate(expected):
        for column, value in enumerate(values):
            actual = predicted[row][column] if row < len(predicted) and column < len(predicted[row]) else None
            if actual is None or whitespace(value) != whitespace(actual):
                errors.append(dict(row=row, column=column, expected=value, actual=actual))
                if len(errors) == limit:
                    return errors
    return errors


def evaluate(runs: list[Path]) -> dict:
    from docling_core.types.doc import DoclingDocument
    from graph_builder.ingestion.scoring import bbox_iou, match_table, score_grid, score_values, score_order, predicted_page
    from .chunking import page_texts
    files, tables, forms, chunks, directories = {}, [], [], [], {}
    for run in runs:
        bundle = run / 'bundle'
        new_files = {row['file_id']: row for row in records(bundle / 'files.jsonl') if row['file_id'] not in files}
        files.update(new_files)
        for name, target in [('tables', tables), ('forms', forms), ('chunks', chunks)]:
            target.extend(row for row in records(bundle / (name + '.jsonl')) if row['file_id'] in new_files)
        for fid, row in new_files.items():
            directories[row['doc_id']] = run / 'work' / row['doc_id']
    by_doc = {row['doc_id']: row for row in files.values()}
    results = {'format': 'annotation-evaluation',
               'quote_normalization': 'Typographic single quotes and primes become ASCII apostrophes; typographic double quotes and double primes become ASCII quotation marks. Whitespace is collapsed; case is retained.',
               'root_tables': [], 'reading_order': [], 'continued_tables': [], 'forms': [], 'scanned_pages': [],
               'limitations': ['Single annotator with AI assistance; no inter-annotator agreement.',
                    'The header-only continuation extension is informed by reviewed held-out failures; its score is descriptive.',
                    'Unannotated joins are unreviewed, not false positives or true positives.',
                    'Scanned form reading order is conventional; its CER and WER are diagnostic.']}
    annotation_files = [ROOT / 'data/gold/ingestion/tables.json']
    all_root = read(annotation_files[0])
    for gold in all_root:
        if gold['doc_id'] not in by_doc:
            raise ValueError('Annotation source absent from completed corpora: ' + gold['doc_id'])
        expected = csv_rows(annotation_path(gold['csv']))
        if gold['format'] == 'form_fields':
            text = page_texts([c for c in chunks if c['doc_id'] == gold['doc_id']]).get(gold['page'], '')
            score = score_values([row[2] for row in expected[1:]], text)
            record = dict(id=gold['id'], format=gold['format'], **score)
        else:
            table, overlap = match_table(gold, tables)
            predicted = table['grid'] if table else []
            record = dict(id=gold['id'], format=gold['format'], iou=overlap,
                          **score_grid(expected, predicted, gold['header_rows']), errors=grid_errors(expected, predicted))
        results['root_tables'].append(record)
    for path in sorted((ROOT / 'data/gold/ingestion/pages').glob('*.json')):
        annotation_files.append(path)
        gold = read(path)
        with gzip.open(directories[gold['doc_id']] / 'native.json.gz', 'rt', encoding='utf-8') as stream:
            document = DoclingDocument.model_validate_json(stream.read())
        predicted = predicted_page(document, gold['page'], read(BASE / 'configs/prototype.json')['corpus']['filters'])
        results['reading_order'].append(dict(doc_id=gold['doc_id'], page=gold['page'], **score_order(gold, predicted)))
    # Manifest locations are current; paths stored inside the frozen manifests resolve through annotation_path.
    for split, folder in [('development', BASE / 'annotations/development'), ('held-out', BASE / 'annotations/held-out')]:
        manifest = folder / 'continued-tables/continued_tables.json'
        annotation_files.append(manifest)
        for gold in read(manifest):
            expected = csv_rows(annotation_path(gold['csv']))
            first = gold['parts'][0]
            candidates = [(bbox_iou(part['bbox'], first['bbox']), table) for table in tables if table['doc_id'] == gold['doc_id']
                          for part in table['parts'] if part['page'] == first['page']]
            overlap, target = max(candidates, key=lambda item: item[0], default=(0, None))
            target = target if overlap else None
            predicted = target['grid'] if target else []
            caught = []
            for left, right in zip(gold['parts'], gold['parts'][1:]):
                found = any(any(p['page'] == left['page'] and bbox_iou(p['bbox'], left['bbox']) > 0 for p in table['parts'])
                            and any(p['page'] == right['page'] and bbox_iou(p['bbox'], right['bbox']) > 0 for p in table['parts'])
                            for table in tables if table['doc_id'] == gold['doc_id'])
                caught.append(dict(pages=[left['page'], right['page']], caught=found))
            headers = bool(target and len(target['parts']) == len(gold['parts']) and all(
                [[whitespace(cell) for cell in row] for row in part['header']] ==
                [[whitespace(cell) for cell in row] for row in expected[:gold['header_rows']]] for part in target['parts']))
            results['continued_tables'].append(dict(id=gold['id'], split=split, iou=overlap,
                join_pairs=caught, header_attached_everywhere=headers, **score_grid(expected, predicted, gold['header_rows']),
                errors=grid_errors(expected, predicted), join=target['join'] if target else None))
        manifest = folder / 'forms/forms.json'
        annotation_files.append(manifest)
        for gold in read(manifest):
            source = csv_rows(annotation_path(gold['csv']))
            expected = [(row[1], row[2]) for row in source[1:]]
            target = next((form for form in forms if form['doc_id'] == gold['doc_id'] and form['page'] == gold['page']), None)
            results['forms'].append(dict(id=gold['id'], split=split, method=target['method'] if target else None,
                **pair_score(expected, target['fields'] if target else [], target['reference_text'] if target else ''),
                **annotated_box_coverage(gold['pairs'], target['fields'] if target else [])))
    manifest = BASE / 'annotations/development/scanned-pages/transcriptions.json'
    annotation_files.append(manifest)
    for gold in read(manifest):
        with gzip.open(directories[gold['doc_id']] / 'native.json.gz', 'rt', encoding='utf-8') as stream:
            data = __import__('json').load(stream)
        # Use the registered serialization: native text items, then native table cells.
        page = gold['page']
        actual = '\n'.join([item['text'] for item in data['texts'] if any(p['page_no'] == page for p in item['prov'])]
                          + [cell['text'] for table in data['tables'] if any(p['page_no'] == page for p in table['prov'])
                             for cell in table['data']['table_cells']])
        expected = annotation_path(gold['text']).read_text(encoding='utf-8')
        results['scanned_pages'].append(dict(id=gold['id'], page=page,
            raw=transcription(expected, actual, gold['critical_tokens']),
            normalized=transcription(expected, actual, gold['critical_tokens'], True)))
    positive = [pair for row in results['continued_tables'] for pair in row['join_pairs']]
    annotated_joins = sum(pair['caught'] for pair in positive)
    predicted_joins = sum(len(table['parts']) - 1 for table in tables)
    results['joins'] = dict(positive_pairs=len(positive), positive_pairs_joined=annotated_joins,
        recall=annotated_joins / len(positive), predicted_joins=predicted_joins,
        reviewed_correct=annotated_joins, reviewed_wrong=0, unreviewed_predictions=predicted_joins - annotated_joins,
        precision_on_reviewed=1.0 if annotated_joins else None, corpus_precision=None,
        policy='Only annotated positive boundaries are reviewed. Corpus precision is unknown until the other predictions are labeled.')
    grids = [row for row in results['root_tables'] if row['format'] == 'grid']
    cell_count = sum(row['cell_count'] for row in grids)
    results['totals'] = {'grid_cell_matches': sum(row['cell_matches'] for row in grids),
                         'grid_cell_count': cell_count,
                         'grid_cell_accuracy': sum(row['cell_matches'] for row in grids) / cell_count,
                         'form_pair_matches': sum(row['matched'] for row in results['forms']),
                         'form_pair_count': sum(row['gold_pairs'] for row in results['forms']),
                         'literal_source_absent_form_values': sum(row['literal_source_absent_count'] for row in results['forms'])}
    for mode in ('raw', 'normalized'):
        rows = [row[mode] for row in results['scanned_pages']]
        prose = [row[mode] for row in results['scanned_pages'] if row['page'] in (23, 24)]
        characters = sum(row['reference_characters'] for row in rows)
        words = sum(row['reference_words'] for row in rows)
        results['totals']['ocr_' + mode] = dict(
            critical_matches=sum(row['critical_matches'] for row in rows), critical_count=sum(row['critical_count'] for row in rows),
            CER=sum(row['character_edits'] for row in rows) / characters,
            WER=sum(row['word_edits'] for row in rows) / words,
            prose_CER=sum(row['character_edits'] for row in prose) / sum(row['reference_characters'] for row in prose),
            word_recall=sum(row['word_recall_matches'] for row in rows) / words)
    results['inputs'] = {'bundle_checksums': {run.relative_to(BASE).as_posix(): digest(run / 'bundle/SHA256SUMS') for run in runs},
                         'annotation_manifests': {path.relative_to(ROOT).as_posix(): digest(path) for path in annotation_files}}
    return results


def markdown(value: dict) -> str:
    lines = ['# Annotation evaluation', '', '| Annotation | Set | Metric | Result |', '| --- | --- | --- | --- |']
    for row in value['root_tables']:
        metric = 'cell_accuracy' if row['format'] == 'grid' else 'value_recall'
        lines.append(f"| {row['id']} | repository | {metric.replace('_', ' ')} | {row[metric]:.2%} |")
    for row in value['continued_tables']:
        count = sum(pair['caught'] for pair in row['join_pairs'])
        lines.append(f"| {row['id']} | {row['split']} | cells; joins; headers | {row['cell_accuracy']:.2%}; {count}/{len(row['join_pairs'])}; {row['header_attached_everywhere']} |")
    for row in value['forms']:
        lines.append(f"| {row['id']} | {row['split']} | exact pairs; bbox presence | {row['matched']}/{row['gold_pairs']}; {row['bbox_share']:.2%} |")
    for row in value['scanned_pages']:
        raw, normalized = row['raw'], row['normalized']
        lines.append(f"| {row['id']} | development | critical raw / normalized; CER normalized; word recall | {raw['critical_matches']}/{raw['critical_count']} / {normalized['critical_matches']}/{normalized['critical_count']}; {normalized['CER']:.2%}; {normalized['word_recall']:.2%} |")
    return '\n'.join(lines) + '\n'


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, nargs='+', default=[BASE / 'runs/prototype/ak3', BASE / 'runs/prototype/reports'])
    args = parser.parse_args()
    result = evaluate([path.resolve() for path in args.runs])
    write(BASE / 'results/evaluation.json', result)
    (BASE / 'results/evaluation.md').write_text(markdown(result), encoding='utf-8')
    print('Evaluation written; conversion was not repeated.')


if __name__ == '__main__':
    main()
