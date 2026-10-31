"""Run resumable local corpora and publish validated K1 bundles."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import os
import subprocess
import sys
import time

from .runtime import BASE, ROOT, canonical, digest, jsonl, read, records, write


def identity(settings: dict) -> str:
    """Include conversion code, schemas, configuration and pinned parser assets."""
    files = ['convert.py', 'rotation.py', 'ocr.py', 'tables.py', 'forms.py', 'text_layer.py',
             'chunking.py', 'ids.py', 'runtime.py', 'cli.py', 'export.py', 'validate.py']
    material = {'settings': settings,
        'modules': {name: digest(Path(__file__).parent / name) for name in files},
        'schemas': {p.name: digest(p) for p in sorted((BASE / 'schemas').glob('k1_*.json'))},
        'template': digest(BASE / 'configs/rimbase_form_template.json'),
        'types': digest(BASE / 'configs/document_types.json'),
        'versions': {name: importlib.metadata.version(name) for name in ('docling', 'docling-core', 'pypdfium2', 'torch')},
        'assets': read(BASE / 'configs/inputs.lock.json')['runtime']}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def process(row: dict, run: Path, settings: dict, fingerprint: str, refresh: bool = False) -> Path:
    from docling_core.types.doc import DoclingDocument
    from graph_builder.corpus.analysis import analyze_pdf, segments
    from graph_builder.corpus.chunking import chunk_document
    from graph_builder.corpus.process import assess_pages
    from .chunking import map_children, page_texts
    from .convert import segment
    from .forms import extract_auto
    from .ids import file_id
    from .ocr import prepass
    from .rotation import retry
    from .tables import continued_tables
    started = time.perf_counter()
    source = ROOT / row['path']
    source_sha = digest(source)
    directory = run / 'work' / row['doc_id']
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / 'complete.json'
    if marker.exists() and not refresh:
        completed = read(marker)
        if completed['identity'] != fingerprint or completed['source_sha256'] != source_sha:
            raise ValueError('Existing run has a different pipeline or source; choose an empty run directory')
        if all(digest(directory / name) == value for name, value in completed['outputs'].items()):
            return directory
    config = settings['corpus']
    analysis = [page.to_dict() for page in analyze_pdf(source, config['analysis'])]
    documents, measurements, engines = [], [], {}
    for mode, first, last in segments([p['mode'] for p in analysis], config['segment_pages']):
        effective_mode, input_pdf, page_range = mode, source, (first, last)
        if mode == 'ocr' and config['ocr']['engine'] == 'ocrmypdf':
            input_pdf, engine = prepass(source, first, directory / 'ocr' / str(first))
            effective_mode, page_range = 'text', None
            engines[first] = engine
        conversion_config = dict(config, ocr=dict(config['ocr']))
        if conversion_config['ocr']['engine'] == 'ocrmypdf':
            # Partial-image OCR remains selectable through the existing corpus engine.
            conversion_config['ocr']['engine'] = 'rapidocr'
        document, meta = segment(input_pdf, effective_mode, page_range,
                                  directory / 'segments' / f'{first}-{last}-{mode}.json.gz', conversion_config)
        documents.append(document)
        measurements.append(dict(meta, pages=[first, last]))
        with (run / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'document': row['doc_id'], 'pages': [first, last], 'cached': meta['cached']}) + '\n')
        print(f"  {row['doc_id']} pages {first}-{last} {'cached' if meta['cached'] else 'converted'}", flush=True)
    merged = documents[0] if len(documents) == 1 else DoclingDocument.concatenate(documents)
    if len(merged.pages) != len(analysis):
        raise ValueError('Concatenated page count differs from the source')
    rotation_config = dict(config, ocr=dict(config['ocr'], engine='rapidocr'))
    merged, rotations = retry(merged, source, directory / 'rotation', rotation_config)
    # Normalize after transformations as well; no live/reloaded divergence downstream.
    merged = DoclingDocument.model_validate_json(merged.model_dump_json())
    chunks, native_tables, _ = chunk_document(merged, row['doc_id'], config,
                                            {p['page'] for p in analysis if p['mode'] != 'text'})
    lookup = {table['table_id']: table['source_ref'] for table in native_tables}
    for chunk in chunks:
        chunk['table_id'] = lookup.get(chunk['table_id'])
        chunk['quality'] = 'ok'
    logical, pairs, header_audit = continued_tables(merged, source, rotations)
    forms = []
    for page in analysis:
        form = extract_auto(source, page['page'], settings['forms']['minimum_label_share'])
        if form:
            forms.append(dict(form, page=page['page']))
    fid = file_id(source_sha)
    types = read(BASE / 'configs/document_types.json')
    dtype = next((r['document_type'] for r in types['rules'] if re.search(r['pattern'], row['doc_id'])), types['default'])
    # Capture the extracted stream independently before assigning identifiers.
    form_text = [{'page': f['page'], 'source_spans': [],
                  'text': '\n'.join(p['key'].rstrip(':') + ': ' + p['value'] for p in f['fields'])} for f in forms]
    expected = page_texts(chunks + form_text)
    children, parents = map_children(fid, row['doc_id'], dtype, chunks, logical, forms)
    assess_pages(analysis, children, config['quality'])
    pages = []
    for page in analysis:
        number = page['page']
        size = merged.pages[number].size
        engine = engines.get(number)
        if not engine and page['mode'] != 'text':
            engine = {'engine': 'rapidocr' if config['ocr']['engine'] == 'ocrmypdf' else config['ocr']['engine'],
                      'version': importlib.metadata.version('rapidocr') if config['ocr']['engine'] in ('ocrmypdf', 'rapidocr') else 'see input lock'}
        pages.append(dict(page_id=f'{fid}:p{number}', file_id=fid, page=number,
            width=size.width, height=size.height, mode=page['mode'], conversion_mode='text' if number in engines else page['mode'],
            parser={'backend': 'docling', 'version': importlib.metadata.version('docling'), 'layout': 'heron', 'table': 'tableformer-fast'},
            ocr=engine, rotation_attempts=[r for r in rotations if r['page'] == number], status=page['status'],
            filtered_text_sha256=hashlib.sha256(expected.get(number, '').encode('utf-8')).hexdigest()))
    flagged = {page['page'] for page in pages if page['status'] != 'ok'}
    for child in children:
        if flagged.intersection(child['pages']):
            child['quality'] = 'review'
    file = dict(file_id=fid, doc_id=row['doc_id'], original_name=source.name, document_type=dtype,
                sha256=source_sha, page_count=len(pages), license=row['license'], text=f'text/{fid}.txt')
    textdir = directory / 'text'
    textdir.mkdir(exist_ok=True)
    (textdir / f'{fid}.txt').write_text('\n\n'.join(c['text'] for c in children), encoding='utf-8')
    for name, rows in [('files', [file]), ('pages', pages), ('tables', logical), ('forms', forms), ('parents', parents), ('chunks', children)]:
        jsonl(directory / (name + '.jsonl'), [canonical(value) for value in rows])
    write(directory / 'joins.json', pairs)
    write(directory / 'headers.json', header_audit)
    write(directory / 'measurements.json', {'segments': measurements, 'document_seconds': round(time.perf_counter() - started, 3)})
    with gzip.open(directory / 'native.json.gz', 'wt', encoding='utf-8') as stream:
        stream.write(merged.model_dump_json())
    outputs = [*directory.glob('*.jsonl'), *textdir.glob('*.txt')]
    write(marker, dict(identity=fingerprint, source_sha256=source_sha,
                       outputs={p.relative_to(directory).as_posix(): digest(p) for p in outputs}))
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', choices=('ak3', 'reports'), default='ak3')
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--only', nargs='*')
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--document-worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    run = args.run.resolve()
    if not run.is_relative_to((BASE / 'runs').resolve()):
        raise ValueError('Run directory must be inside the ignored local runs directory')
    run.mkdir(parents=True, exist_ok=True)
    settings = read(BASE / 'configs/prototype.json')
    fingerprint = identity(settings)
    selected = [row for row in read(BASE / 'configs/corpora.json')[args.corpus] if not args.only or row['doc_id'] in args.only]
    directories = []
    for index, row in enumerate(selected, 1):
        print(f"[{index}/{len(selected)}] {row['doc_id']}", flush=True)
        if args.document_worker:
            directories.append(process(row, run, settings, fingerprint, args.refresh))
        else:
            environment = os.environ.copy()
            environment['PYTHONPATH'] = str(BASE / 'src')
            command = [sys.executable, '-B', '-X', 'faulthandler', '-m', 'ingest_prototype.cli',
                       '--corpus', args.corpus, '--run', str(run), '--only', row['doc_id'], '--document-worker']
            if args.refresh:
                command.append('--refresh')
            completed = subprocess.run(command, env=environment)
            if completed.returncode:
                raise RuntimeError(f'Document worker failed with exit code {completed.returncode}: {row["doc_id"]}')
            directories.append(run / 'work' / row['doc_id'])
    if args.document_worker:
        return
    from .export import publish
    bundle = publish(run, directories, fingerprint, settings)
    print('Validated bundle:', bundle.relative_to(BASE), flush=True)


if __name__ == '__main__':
    main()
