"""Validate schemas, references, offsets, boxes and independent page reconstruction."""
from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path

from .chunking import page_texts
from .export import GROUPS
from .runtime import BASE, digest, read, records


def validate(path: Path) -> dict:
    from jsonschema import Draft202012Validator
    errors = []
    sets = {name: records(path / (name + '.jsonl')) for name in GROUPS}
    singular = {'files': 'file', 'pages': 'page', 'tables': 'table', 'forms': 'form', 'parents': 'parent', 'chunks': 'chunk'}
    for name, rows in sets.items():
        validator = Draft202012Validator(read(BASE / f'schemas/k1_{singular[name]}.schema.json'))
        for row in rows:
            errors.extend(f'{name}: {e.json_path}: {e.message}' for e in validator.iter_errors(row))
        identifiers = [row[singular[name] + '_id'] for row in rows]
        if len(set(identifiers)) != len(rows):
            errors.append(name + ': duplicate IDs')
    files = {row['file_id']: row for row in sets['files']}
    pages = {(row['file_id'], row['page']): row for row in sets['pages']}
    parents = {row['parent_id']: row for row in sets['parents']}
    tables = {row['table_id'] for row in sets['tables']}
    forms = {row['form_id'] for row in sets['forms']}
    texts = {fid: (path / row['text']).read_text(encoding='utf-8') for fid, row in files.items()}
    counters = Counter()
    for name in GROUPS[1:]:
        for row in sets[name]:
            fid = row['file_id']
            if fid not in files:
                errors.append('Missing file reference')
            for number in row.get('pages', [row['page']] if 'page' in row else []):
                if (fid, number) not in pages:
                    errors.append('Missing page reference')
            for region in row.get('regions', []):
                page = pages[(fid, region['page'])]
                l, t, r, b = region['bbox']
                if not (0 <= l <= r <= page['width'] + .01 and 0 <= t <= b <= page['height'] + .01):
                    errors.append(f'Out-of-page region: {name} {row.get("chunk_id", row.get("table_id"))} {region}')
    rebuilt = {}
    for fid in files:
        rebuilt.update({(fid, page): text for page, text in page_texts([c for c in sets['chunks'] if c['file_id'] == fid]).items()})
    matched = 0
    for key, page in pages.items():
        value = hashlib.sha256(rebuilt.get(key, '').encode('utf-8')).hexdigest()
        if value == page['filtered_text_sha256']:
            matched += 1
        else:
            errors.append('Page rebuild differs: ' + page['page_id'])
    for child in sets['chunks']:
        parent = parents.get(child['parent_id'])
        if not parent or parent['file_id'] != child['file_id']:
            errors.append('Invalid parent reference')
        if child['table_id'] and child['table_id'] not in tables:
            errors.append('Invalid table reference')
        if child['form_id'] and child['form_id'] not in forms:
            errors.append('Invalid form reference')
        if child['child_index'] != counters[child['parent_id']]:
            errors.append('Noncontiguous child indices')
        counters[child['parent_id']] += 1
        if texts[child['file_id']][child['char_start']:child['char_end']] != child['text']:
            errors.append('Text offset mismatch')
        for span in child['source_spans']:
            if not 0 <= span['start'] <= span['end'] <= len(child['text']):
                errors.append('Source span out of range')
    for line in (path / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        expected, name = line.split('  ', 1)
        if digest(path / name) != expected:
            errors.append('Checksum mismatch: ' + name)
    return {'status': 'pass' if not errors else 'fail', 'counts': {name: len(rows) for name, rows in sets.items()},
            'page_rebuild_matches': matched, 'page_rebuild_total': len(pages),
            'schemas': not any(': $' in e for e in errors), 'references': not any('reference' in e for e in errors),
            'errors': errors}
