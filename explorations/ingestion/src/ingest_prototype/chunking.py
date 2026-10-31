"""Keep corpus text intact while adding form children and logical table lineage."""
from __future__ import annotations

from collections import Counter
import copy
import hashlib

from .forms import report_context
from .ids import child_id


def separate_contexts(chunks: list[dict], contexts: dict[int, dict]) -> list[dict]:
    """Split cross-page passages when daily-report context changes."""
    result = []
    for chunk in chunks:
        signatures = {tuple(sorted(contexts.get(page, {}).items())) for page in chunk['pages']}
        spans = chunk['source_spans']
        if len(signatures) <= 1 or not spans:
            result.append(chunk)
            continue
        for page in dict.fromkeys(span['page'] for span in spans):
            selected = [span for span in spans if span['page'] == page]
            start, end = min(s['start'] for s in selected), max(s['end'] for s in selected)
            child = copy.deepcopy(chunk)
            child.update(text=chunk['text'][start:end], page=page, pages=[page],
                         regions=[r for r in chunk['regions'] if r['page'] == page],
                         source_spans=[dict(s, start=s['start'] - start, end=s['end'] - start) for s in selected])
            result.append(child)
    return result


def map_children(fid: str, docid: str, dtype: str, chunks: list, tables: list, forms: list) -> tuple:
    owners = {}
    parents = {}
    for index, table in enumerate(tables, 1):
        table['table_id'] = f'{fid}:t{index}'
        table['file_id'], table['doc_id'] = fid, docid
        for part in table['parts']:
            owners[part['source_ref']] = (table['table_id'], part)
        parents[table['table_id']] = dict(parent_id=table['table_id'], type='table', file_id=fid,
                                         pages=table['pages'], section_path=[], document_type=dtype)
    counts = Counter()
    children = []
    previous_path = None
    section = 0
    context = {form['page']: report_context(form) for form in forms}
    for original in separate_contexts(chunks, context):
        chunk = copy.deepcopy(original)
        if previous_path != chunk['section_path'] or not section:
            section += 1
            previous_path = chunk['section_path']
        # Corpus table IDs are replaced by their source references before mapping.
        if chunk['table_id']:
            parent, part = owners[chunk['table_id']]
            chunk['table_id'] = parent
            offset = part['row_start'] - len(part['header']) if part['row_start'] else 0
            chunk['row_start'] = offset + (chunk['row_start'] or 0)
            chunk['row_end'] = min(part['row_end'], offset + (chunk['row_end'] or 0))
        else:
            parent = f'{fid}:s{section}'
        parents.setdefault(parent, dict(parent_id=parent, type='section', file_id=fid,
                                        pages=[], section_path=chunk['section_path'], document_type=dtype))
        parents[parent]['pages'] = sorted(set(parents[parent]['pages']) | set(chunk['pages']))
        chunk.update(chunk_id=child_id(parent, counts[parent]), file_id=fid, parent_id=parent,
                     child_index=counts[parent], context=context.get(chunk['page'], {}), form_id=None)
        counts[parent] += 1
        children.append(chunk)
    for index, form in enumerate(forms, 1):
        parent = f'{fid}:f{index}'
        form.update(form_id=parent, file_id=fid, doc_id=docid)
        parents[parent] = dict(parent_id=parent, type='form', file_id=fid, pages=[form['page']],
                               section_path=[], document_type=dtype)
        # Printed labels already ending in a colon retain their punctuation.
        text = '\n'.join(field['key'].rstrip(':') + ': ' + field['value'] for field in form['fields'])
        regions = [{'page': form['page'], 'bbox': field[key]} for field in form['fields']
                   for key in ('key_bbox', 'value_bbox') if field[key]]
        children.append(dict(chunk_id=child_id(parent, 0), file_id=fid, doc_id=docid, parent_id=parent,
            child_index=0, type='form', text=text, section=None, section_path=[], page=form['page'],
            pages=[form['page']], regions=regions, source_spans=[], table_id=None, form_id=parent,
            row_start=None, row_end=None, language='en', ocr=False,
            quality='ok' if form['verified'] else 'review', context=context.get(form['page'], {})))
    position = 0
    for child in children:
        child['char_start'], child['char_end'] = position, position + len(child['text'])
        child['sha256'] = hashlib.sha256(child['text'].encode('utf-8')).hexdigest()
        position = child['char_end'] + 2
    return children, list(parents.values())


def page_texts(children: list[dict]) -> dict[int, str]:
    result = {}
    for child in children:
        if child['source_spans']:
            for span in child['source_spans']:
                result.setdefault(span['page'], []).append(child['text'][span['start']:span['end']])
        elif child['page'] is not None:
            result.setdefault(child['page'], []).append(child['text'])
    return {page: '\n'.join(parts) for page, parts in result.items()}
