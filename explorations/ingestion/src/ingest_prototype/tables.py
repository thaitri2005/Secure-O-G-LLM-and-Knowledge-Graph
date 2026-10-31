"""Aligned-column continuation decisions with evidence-based header cleaning."""
from __future__ import annotations
from pathlib import Path
from statistics import median
import copy
import re

def continued_tables(document: object, source: Path, rotations: list[dict]) -> tuple:
    """Assemble native parts; preserve physical provenance separately from alignment geometry."""
    from .text_layer import source_page
    data = document.export_to_dict()
    tables = native(data)
    physical = {}
    accepted = {row['page']: row for row in rotations if row['accepted']}

    def upright_box(bb, width, height, degrees):
        if degrees == 90:
            return [height - bb[3], bb[0], height - bb[1], bb[2]]
        if degrees == 270:
            return [bb[1], width - bb[2], bb[3], width - bb[0]]
        return [width - bb[2], height - bb[3], width - bb[0], height - bb[1]]
    sizes = {number: (data['pages'][str(number)]['size']['width'], data['pages'][str(number)]['size']['height']) for number in accepted}
    for table in tables:
        raw = data['tables'][table['native_index']]['data']['table_cells']
        table['raw_cells'] = copy.deepcopy(raw)
        physical[table['id']] = table['bbox'][:]
        attempt = accepted.get(table['page'])
        if attempt:
            width, height = sizes[table['page']]
            table['bbox'] = upright_box(table['bbox'], width, height, attempt['degrees'])
            table['height'] = width if attempt['degrees'] in (90, 270) else height
            for cell in table['raw_cells']:
                if cell.get('bbox'):
                    bb = upright_box(box(cell['bbox'], height), width, height, attempt['degrees'])
                    cell['bbox'] = dict(zip(('l', 't', 'r', 'b'), bb), coord_origin='TOPLEFT')
    for number, attempt in accepted.items():
        width, height = sizes[number]
        if attempt['degrees'] in (90, 270):
            data['pages'][str(number)]['size'].update(width=height, height=width)
        for text in data['texts']:
            for prov in text.get('prov', []):
                if prov['page_no'] == number:
                    bb = upright_box(box(prov['bbox'], height), width, height, attempt['degrees'])
                    prov['bbox'] = dict(zip(('l', 't', 'r', 'b'), bb), coord_origin='TOPLEFT')
    pairs = []
    for left in tables:
        for right in tables:
            if right['page'] != left['page'] + 1:
                continue
            status, reasons, alignment = aligned_decision(left, right, data, tables)
            lp = [t for t in tables if t['page'] == left['page'] and (not furniture(t) or len(t['grid']) == 1)]
            rp = [t for t in tables if t['page'] == right['page'] and (not furniture(t))]
            header_only = len(left['grid']) == 1 and left['header_rows'] == 1 and (left['num_cols'] >= 2) and (left['num_cols'] == right['num_cols'])
            if header_only and lp and rp and (left is lp[-1]) and (right is rp[0]):
                width = data['pages'][str(left['page'])]['size']['width']
                aligned = max((abs(left['bbox'][k] - right['bbox'][k]) for k in (0, 2))) <= 0.03 * width
                mapping, reason = column_map(left, right)
                if aligned and (not reason) and (mapping['right_to_left'] == list(range(left['num_cols']))):
                    status, reasons, alignment = ('joined', ['header_only_extension_informed_by_review'], mapping)
            pairs.append({'left': left['id'], 'right': right['id'], 'left_page': left['page'], 'right_page': right['page'], 'status': status, 'reasons': reasons, 'alignment': alignment})
    logical = assemble(tables, pairs, source.stem)
    pages = {p['page'] for table in logical if len(table['parts']) > 1 for p in table['parts']}
    layers = {page: source_page(source, page) for page in pages}
    for number, layer in layers.items():
        if number in accepted:
            width, height = sizes[number]
            degrees = accepted[number]['degrees']
            for word in layer['words']:
                word['bbox'] = upright_box(word['bbox'], width, height, degrees)
            if degrees in (90, 270):
                layer['width'], layer['height'] = (height, width)
    header_audit = repair_headers(logical, tables, layers)
    for table in logical:
        table['regions'] = [{'page': part['page'], 'bbox': physical[part['source_ref']]} for part in table['parts']]
        for part in table['parts']:
            part['bbox'] = physical[part['source_ref']]
    return (logical, pairs, header_audit)

def norm(text: str) -> str:
    """Collapse whitespace without changing case."""
    return ' '.join(text.split())

def box(raw: dict | None, height: float) -> list | None:
    """Convert a native rectangle to top-left coordinates."""
    if not raw:
        return None
    if raw.get('coord_origin') == 'BOTTOMLEFT':
        return [raw['l'], height - raw['t'], raw['r'], height - raw['b']]
    return [raw['l'], raw['t'], raw['r'], raw['b']]

def native(data: dict) -> list[dict]:
    """Read anchor cells and column geometry from a native document."""
    result = []
    for index, table in enumerate(data['tables']):
        if not table['prov']:
            continue
        p = table['prov'][0]['page_no']
        height = data['pages'][str(p)]['size']['height']
        cells = table['data']['table_cells']
        grid = [[''] * table['data']['num_cols'] for _ in range(table['data']['num_rows'])]
        for cell in cells:
            grid[cell['start_row_offset_idx']][cell['start_col_offset_idx']] = cell['text']
        headers = 0
        for row in range(len(grid)):
            if any((c.get('column_header') for c in cells if c['start_row_offset_idx'] == row)):
                headers += 1
            else:
                break
        bounds = box(table['prov'][0]['bbox'], height)
        widths = []
        for column in range(table['data']['num_cols']):
            values = [box(c.get('bbox'), height) for c in cells if c['start_col_offset_idx'] == column and c['col_span'] == 1]
            values = [b for b in values if b]
            widths.append(min((b[0] for b in values), default=None))
        if bounds and bounds[2] > bounds[0] and all((v is not None for v in widths)):
            widths = [(v - bounds[0]) / (bounds[2] - bounds[0]) for v in widths] + [1.0]
        else:
            widths = None
        result.append({'id': table['self_ref'], 'page': p, 'bbox': bounds, 'height': height, 'num_cols': table['data']['num_cols'], 'grid': grid, 'header_rows': headers, 'widths': widths, 'native_index': index, 'cells': [{'r': c['start_row_offset_idx'], 'c': c['start_col_offset_idx'], 'row_span': c['row_span'], 'col_span': c['col_span'], 'text': c['text'], 'is_header': c.get('column_header', False) or c.get('row_header', False) or c.get('row_section', False)} for c in cells]})
    return sorted(result, key=lambda t: (t['page'], t['bbox'][1], t['native_index']))

def furniture(table: dict) -> bool:
    """Identify compact margin tables that repeat page furniture."""
    height = table['height']
    bb = table['bbox']
    return (bb[3] <= 0.2 * height or bb[1] >= 0.85 * height) and bb[3] - bb[1] <= 0.08 * height and (len(table['grid']) <= 6) and (sum((len(c.split()) for row in table['grid'] for c in row)) <= 20)

def tokens(table: dict) -> set[str]:
    """Collect the native column-heading vocabulary."""
    return set(re.findall('\\w+', ' '.join((' '.join(r) for r in table['grid'][:table['header_rows']])).casefold()))

def extent(table: dict, column: int, prefer_header: bool) -> list | None:
    """Estimate a column extent using median cell edges."""
    cells = [c for c in table['raw_cells'] if c['start_col_offset_idx'] == column and c['col_span'] == 1 and c.get('bbox')]
    preferred = [c for c in cells if (c['start_row_offset_idx'] < table['header_rows']) == prefer_header]
    selected = preferred or cells
    if not selected:
        return None
    return [median((c['bbox']['l'] for c in selected)), median((c['bbox']['r'] for c in selected))]

def column_map(left: dict, right: dict) -> tuple:
    """Map continuation columns by their horizontal overlap."""
    extents = [extent(left, c, True) for c in range(left['num_cols'])]
    if any((v is None for v in extents)):
        return (None, 'left_column_geometry_missing')
    boundaries = [left['bbox'][0]] + [(a[1] + b[0]) / 2 for a, b in zip(extents, extents[1:])] + [left['bbox'][2]]
    if any((a >= b for a, b in zip(boundaries, boundaries[1:]))):
        return (None, 'left_bins_nonmonotonic')
    mapped, coverage = ([], [])
    for c in range(right['num_cols']):
        bb = extent(right, c, False)
        if bb is None or bb[1] <= bb[0]:
            mapped.append(None)
            coverage.append(0)
            continue
        overlaps = [max(0, min(bb[1], end) - max(bb[0], start)) / (bb[1] - bb[0]) for start, end in zip(boundaries, boundaries[1:])]
        best = max(range(len(overlaps)), key=overlaps.__getitem__)
        mapped.append(best if overlaps[best] >= 0.6 else None)
        coverage.append(overlaps[best])
    nonempty = {c['start_col_offset_idx'] for c in right['raw_cells'] if c['text'].strip()}
    if any((mapped[c] is None for c in nonempty)):
        return (None, 'nonempty_column_unmapped')
    located = [v for v in mapped if v is not None]
    if len(located) < 0.85 * right['num_cols']:
        return (None, 'column_mapping_coverage_below_85_percent')
    if located != sorted(located):
        return (None, 'column_mapping_nonmonotonic')
    return ({'right_to_left': mapped, 'overlap': coverage, 'left_boundaries': boundaries}, None)

def repeated_heading(text: dict, prov: dict, data: dict, left: dict, right: dict) -> bool:
    """Distinguish repeated margin headings from intervening body headings."""
    p = prov['page_no']
    h = data['pages'][str(p)]['size']['height']
    bb = box(prov['bbox'], h)
    if not (bb[3] <= 0.2 * h or bb[1] >= 0.85 * h):
        return False
    return any((norm(other['text']) == norm(text['text']) and any((q['page_no'] != p and q['page_no'] in (left['page'], right['page']) and (box(q['bbox'], data['pages'][str(q['page_no'])]['size']['height'])[3] <= 0.2 * data['pages'][str(q['page_no'])]['size']['height'] or box(q['bbox'], data['pages'][str(q['page_no'])]['size']['height'])[1] >= 0.85 * data['pages'][str(q['page_no'])]['size']['height']) for q in other.get('prov', []))) for other in data['texts']))

def aligned_decision(left: dict, right: dict, data: dict, tables: list[dict]) -> tuple:
    """Apply the registered margin, heading and column-alignment checks."""
    lp = [t for t in tables if t['page'] == left['page'] and (not furniture(t))]
    rp = [t for t in tables if t['page'] == right['page'] and (not furniture(t))]
    if not lp or not rp or left['id'] != lp[-1]['id'] or (right['id'] != rp[0]['id']):
        return ('single', ['not_last_first_after_furniture'], {})
    if left['bbox'][3] < 0.8 * left['height'] or right['bbox'][1] > 0.25 * right['height']:
        return ('single', ['continuation_margins_failed'], {})
    width = data['pages'][str(left['page'])]['size']['width']
    if max((abs(left['bbox'][k] - right['bbox'][k]) for k in (0, 2))) > 0.03 * width:
        return ('single', ['table_x_edges_differ'], {})
    if not left['header_rows']:
        return ('single', ['missing_left_header'], {})
    a, b = (tokens(left), tokens(right))
    similarity = len(a & b) / len(a | b) if a | b else 0
    if right['header_rows'] and similarity < 0.45:
        return ('single', ['header_jaccard_below_0.45'], {'header_jaccard': similarity})
    for text in data['texts']:
        if text['label'] not in ('section_header', 'title'):
            continue
        for prov in text.get('prov', []):
            p = prov['page_no']
            if p not in (left['page'], right['page']):
                continue
            bb = box(prov['bbox'], data['pages'][str(p)]['size']['height'])
            between = p == left['page'] and bb[1] >= left['bbox'][3] or (p == right['page'] and bb[3] <= right['bbox'][1])
            if between and (not repeated_heading(text, prov, data, left, right)):
                return ('single', ['heading_between', text['text']], {'header_jaccard': similarity})
    mapping, reason = column_map(left, right)
    if reason:
        return ('single', [reason], {'header_jaccard': similarity})
    identity = left['num_cols'] == right['num_cols'] and mapping['right_to_left'] == list(range(left['num_cols']))
    return ('joined' if identity else 'uncertain', ['boundary_after_furniture', 'continuation_margins', 'aligned_x_edges', 'similar_header' if right['header_rows'] else 'no_continuation_header', 'no_intervening_body_heading', 'identity_column_map' if identity else 'column_count_or_mapping_changed'], dict(mapping, header_jaccard=similarity))

def assemble(tables: list[dict], pairs: list[dict], docid: str) -> list[dict]:
    """Project linked native parts into one logical column frame."""
    links = {p['right']: p for p in pairs if p['status'] in ('joined', 'uncertain')}
    owner, logical = ({}, [])
    for t in tables:
        link = links.get(t['id'])
        part = {'source_ref': t['id'], 'page': t['page'], 'bbox': t['bbox'], 'native_grid': copy.deepcopy(t['grid']), 'native_cells': t['cells']}
        if link and link['left'] in owner:
            target = owner[link['left']]
            mapping = link['alignment']['right_to_left']
            previous = target['parts'][-1]['column_map']
            mapping = [previous[c] if c is not None and c < len(previous) else None for c in mapping]
            start = len(target['grid'])
            for row in t['grid'][t['header_rows']:]:
                projected = [''] * target['num_cols']
                for c, value in enumerate(row):
                    anchor = mapping[c]
                    if anchor is not None and value:
                        projected[anchor] = '\n'.join((v for v in (projected[anchor], value) if v))
                target['grid'].append(projected)
            for cell in t['cells']:
                if cell['r'] < t['header_rows']:
                    continue
                columns = [mapping[c] for c in range(cell['c'], min(len(mapping), cell['c'] + cell['col_span'])) if mapping[c] is not None]
                if columns:
                    target['cells'].append(dict(cell, r=start + cell['r'] - t['header_rows'], c=min(columns), col_span=max(columns) - min(columns) + 1))
            part.update(row_start=start, row_end=len(target['grid']), header=copy.deepcopy(target['grid'][:target['header_rows']]), column_map=mapping)
            target['parts'].append(part)
            target['pages'].append(t['page'])
            target['join']['status'] = 'uncertain' if 'uncertain' in (target['join']['status'], link['status']) else 'joined'
            target['join']['reasons'].extend(link['reasons'])
        else:
            part.update(row_start=0, row_end=len(t['grid']), header=t['grid'][:t['header_rows']], column_map=list(range(t['num_cols'])))
            target = {'logical_id': f"{docid}:{t['id']}", 'doc_id': docid, 'pages': [t['page']], 'grid': copy.deepcopy(t['grid']), 'header_rows': t['header_rows'], 'num_cols': t['num_cols'], 'cells': copy.deepcopy(t['cells']), 'parts': [part], 'join': {'status': 'single', 'reasons': []}}
            logical.append(target)
        owner[t['id']] = target
    for t in logical:
        t.update(num_rows=len(t['grid']), rows_text=['; '.join(row) for row in t['grid'][t['header_rows']:]], regions=[{'page': p['page'], 'bbox': p['bbox']} for p in t['parts']])
    return logical

def tokenized(text: str) -> list[str]:
    """Keep punctuation while splitting a heading into tokens."""
    return re.findall('\\S+', text)

def repair_headers(logical: list[dict], tables: list[dict], layers: dict) -> list[dict]:
    """Choose the least polluted repeated heading and remove supported furniture."""
    by_ref = {t['id']: t for t in tables}
    evidence = []
    for target in logical:
        if len(target['parts']) < 2:
            continue
        choices = []
        for part in target['parts']:
            table = by_ref[part['source_ref']]
            if not table['header_rows']:
                continue
            layer = layers[part['page']]
            bb = table['bbox']
            height = layer['height']
            outside = [w['text'] for w in layer['words'] if (w['bbox'][3] <= bb[1] or w['bbox'][1] >= bb[3]) and (w['bbox'][3] <= bb[1] or w['bbox'][3] <= 0.2 * height or w['bbox'][1] >= 0.85 * height)]
            furniture = {t.casefold() for t in outside}
            mapping = part['column_map']
            header = []
            for row in table['grid'][:table['header_rows']]:
                projected = [''] * target['num_cols']
                for col, value in enumerate(row):
                    dest = mapping[col]
                    if dest is not None:
                        projected[dest] = ' '.join((v for v in (projected[dest], value) if v))
                header.append(projected)
            choices.append({'page': part['page'], 'header': header, 'furniture': furniture, 'pollution': sum((t.casefold() in furniture for row in header for cell in row for t in tokenized(cell)))})
        if not choices:
            continue
        selected = min(choices, key=lambda c: (c['pollution'], sum((len(tokenized(v)) for row in c['header'] for v in row)), c['page']))
        cleaned = copy.deepcopy(selected['header'])
        removed = []
        if len(choices) > 1:
            for ri, row in enumerate(cleaned):
                for ci, value in enumerate(row):
                    shared = set.intersection(*[{t.casefold() for t in tokenized(c['header'][ri][ci])} for c in choices if len(c['header']) == len(cleaned)])
                    keep = []
                    for token in tokenized(value):
                        if token.casefold() in selected['furniture'] and token.casefold() not in shared:
                            removed.append({'row': ri, 'column': ci, 'token': token, 'same_page_outside_table': True})
                        else:
                            keep.append(token)
                    cleaned[ri][ci] = ' '.join(keep)
        original = copy.deepcopy(target['grid'][target['header_rows']:])
        if len(cleaned) != target['header_rows']:
            evidence.append({'logical_id': target['logical_id'], 'status': 'header-row-count mismatch; retained native header'})
            continue
        target['grid'][:target['header_rows']] = cleaned
        for part in target['parts']:
            part['header'] = copy.deepcopy(cleaned)
        for cell in target['cells']:
            if cell['r'] < target['header_rows']:
                cell['text'] = cleaned[cell['r']][cell['c']]
        assert original == target['grid'][target['header_rows']:]
        evidence.append({'logical_id': target['logical_id'], 'selected_page': selected['page'], 'candidates': [{'page': c['page'], 'outside_token_overlap': c['pollution'], 'header': c['header']} for c in choices], 'removed': removed, 'selected_header': cleaned, 'data_cells_unchanged': True})
    return evidence
