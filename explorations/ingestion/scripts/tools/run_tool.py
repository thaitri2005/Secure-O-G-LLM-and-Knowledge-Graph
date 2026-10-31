"""Small local-only study harness; output page numbers refer to study slices."""
import argparse
import csv
import importlib.metadata
import json
import os
from pathlib import Path
import re
import time
import traceback

BASE = Path(__file__).resolve().parents[2]
for key, value in {
    'HF_HOME': BASE / '.cache/huggingface', 'TORCH_HOME': BASE / '.cache/torch',
    'XDG_CACHE_HOME': BASE / '.cache', 'PADDLE_PDX_CACHE_HOME': BASE / '.cache/paddlex',
    'MINERU_HOME': BASE / '.cache/mineru', 'TEMP': BASE / '.cache/tmp',
    'TMP': BASE / '.cache/tmp',
}.items():
    os.environ[key] = str(value.resolve())
os.environ.update(HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1',
                  PADDLE_PDX_MODEL_SOURCE='HuggingFace', PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True', PYTHONUTF8='1')


def clean(value):
    text = str(value).replace(str(Path.cwd()), '<repository>')
    text = text.replace(str(Path.home()), '<profile>')
    return text


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True, default=str) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('tool', choices=['docling', 'pdfplumber', 'camelot', 'opendataloader-pdf', 'paddleocr', 'mineru', 'ocrmypdf'])
    parser.add_argument('--variant', default='standard')
    parser.add_argument('--case', default=None)
    args = parser.parse_args()
    name = args.tool + ('-' + args.variant if args.variant != 'standard' else '')
    output = BASE / 'runs' / name
    output.mkdir(parents=True, exist_ok=True)
    cases = json.loads((BASE / 'configs/pages.json').read_text())['cases']
    converter = None
    history = output / "run.json"
    rows = json.loads(history.read_text()) if args.case and history.exists() else []
    rows = [row for row in rows if row.get("case") != args.case] if args.case else rows
    for case in cases:
        sid = case['id']
        if args.case and args.case != sid:
            continue
        row = dict(case=sid, source_doc_id=case['doc_id'], physical_pages=case['pages'],
                   output_page_numbering='One-based within slice; use physical_pages for source mapping.')
        started = time.perf_counter()
        target = output / sid
        target.mkdir(exist_ok=True)
        source = BASE / 'runs/pages' / (sid + '.pdf')
        try:
            if args.tool in ['pdfplumber', 'camelot'] and sid not in ['ak3-abbreviations', 'ak3-daily-operations', 'ak3-nonproductive-time']:
                row.update(status='skipped', reason='Digital-table subset is ak3-abbreviations, ak3-daily-operations, ak3-nonproductive-time.')
                rows.append(row)
                save(target / 'status.json', row)
                continue
            if args.tool == 'mineru':
                os.environ.update(MINERU_MODEL_SMALL_BACKEND='onnx', MINERU_MODEL_VLM_ENGINE='llama-cpp',
                    MINERU_MODEL_VLM_SERVER_URL='http://127.0.0.1:8087', MINERU_MODEL_VLM_MAX_CONCURRENCY='1')
                from mineru.parser.mineru_parser import MinerUParser
                if converter is None:
                    converter = MinerUParser(tier='standard')
                result = converter.parse(source)
                save(target / 'middle.json', result.to_dict())
                (target / 'document.md').write_text(result.markdown(), encoding='utf-8')
                row.update(version=importlib.metadata.version('mineru'),
                    model_deviation='2604 endpoint shared with Docling; upstream default is 2605.',
                    merge='Default structural merging; optional LLM-aided cell merge disabled.')
            elif args.tool == 'ocrmypdf':
                if sid not in ['ak3-scanned-well-schematic', 'ak3-scanned-permit-letter']:
                    row.update(status='skipped', reason='OCR derivative experiment uses ak3-scanned-well-schematic and ak3-scanned-permit-letter.')
                    rows.append(row)
                    save(target / 'status.json', row)
                    continue
                native = (BASE / '.cache/tesseract').resolve()
                os.environ['PATH'] = str(native) + os.pathsep + os.environ['PATH']
                os.environ['TESSDATA_PREFIX'] = str(native / 'tessdata')
                import ocrmypdf
                ocrmypdf.ocr(str(source), str(target / 'ocr.pdf'), language=['eng'],
                            force_ocr=True, deskew=True, rotate_pages=True,
                            sidecar=str(target / 'text.txt'), progress_bar=False,
                            output_type='pdf', optimize=0)
                row['version'] = importlib.metadata.version('ocrmypdf')
            elif args.tool == 'pdfplumber':
                import pdfplumber
                tables = []
                with pdfplumber.open(source) as pdf:
                    for number, page in enumerate(pdf.pages, 1):
                        (target / f'page-{number}.md').write_text(page.extract_text() or '', encoding='utf-8')
                        for idx, table in enumerate(page.find_tables()):
                            grid = table.extract()
                            tables.append(dict(page=number, bbox=table.bbox, cells=table.cells, rows=grid))
                            with (target / f'page-{number}-table-{idx}.csv').open('w', newline='', encoding='utf-8') as file:
                                csv.writer(file).writerows(grid)
                save(target / 'tables.json', tables)
                row.update(tables=len(tables), version=importlib.metadata.version('pdfplumber'))
            elif args.tool == 'camelot':
                import camelot
                tables = camelot.read_pdf(str(source), pages='all', flavor='lattice')
                saved = []
                for idx, table in enumerate(tables):
                    table.df.to_csv(target / f'table-{idx}.csv', index=False, header=False)
                    saved.append(dict(page=table.page, bbox=table._bbox, rows=table.df.values.tolist(),
                                      report=table.parsing_report))
                save(target / 'tables.json', saved)
                row.update(tables=len(tables), version=importlib.metadata.version('camelot-py'))
            elif args.tool == 'opendataloader-pdf':
                import opendataloader_pdf
                hybrid = dict(hybrid='docling-fast', hybrid_mode='full',
                              hybrid_url='http://127.0.0.1:5002') if args.variant == 'hybrid' else {}
                opendataloader_pdf.convert(input_path=[str(source)], output_dir=str(target),
                                           format='json,markdown', quiet=True, **hybrid)
                row['version'] = importlib.metadata.version('opendataloader-pdf')
            elif args.tool == 'docling':
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import PdfPipelineOptions, TableStructureV2Options, EasyOcrOptions
                from docling.datamodel.accelerator_options import AcceleratorOptions
                from docling.document_converter import DocumentConverter, PdfFormatOption
                if converter is None:
                    opts = PdfPipelineOptions(do_ocr=True, accelerator_options=AcceleratorOptions(device='cpu', num_threads=6))
                    opts.ocr_options = EasyOcrOptions(lang=['en'], use_gpu=False,
                        model_storage_directory=str(BASE / 'models/corpus-ocr'), download_enabled=False)
                    if args.variant == 'alternate-tables':
                        opts.table_structure_options = TableStructureV2Options()
                    fmt = PdfFormatOption(pipeline_options=opts)
                    if args.variant == 'vlm':
                        from docling.datamodel.pipeline_options import VlmPipelineOptions
                        from docling.datamodel.pipeline_options import VlmConvertOptions
                        from docling.datamodel.vlm_engine_options import ApiVlmEngineOptions, VlmEngineType
                        from docling.pipeline.vlm_pipeline import VlmPipeline
                        vlm = VlmConvertOptions.from_preset('mineru2_pro', engine_options=ApiVlmEngineOptions(
                            engine_type=VlmEngineType.API, url='http://127.0.0.1:8087/v1/chat/completions',
                            timeout=300, concurrency=1))
                        fmt = PdfFormatOption(pipeline_cls=VlmPipeline, pipeline_options=VlmPipelineOptions(
                            vlm_options=vlm, enable_remote_services=True))
                    converter = DocumentConverter(format_options={InputFormat.PDF: fmt})
                result = converter.convert(source)
                document = result.document
                save(target / 'document.json', document.export_to_dict())
                (target / 'document.md').write_text(document.export_to_markdown(), encoding='utf-8')
                for idx, table in enumerate(document.tables):
                    table.export_to_dataframe(doc=document).to_csv(target / f'table-{idx}.csv', index=False)
                row.update(conversion_status=result.status.value, tables=len(document.tables),
                           key_value_items=len(document.key_value_items), version=importlib.metadata.version('docling'))
                if args.variant == 'standard':
                    from docling_core.transforms.chunker import HybridChunker
                    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
                    from transformers import AutoTokenizer
                    tokenizer = HuggingFaceTokenizer(tokenizer=AutoTokenizer.from_pretrained(
                        'sentence-transformers/all-MiniLM-L6-v2',
                        revision='1110a243fdf4706b3f48f1d95db1a4f5529b4d41', local_files_only=True), max_tokens=512)
                    chunks = list(HybridChunker(tokenizer=tokenizer).chunk(document))
                    save(target / 'hybrid-chunks.json', [c.model_dump(mode='json') for c in chunks])
                    row['hybrid_chunks'] = len(chunks)
            elif args.tool == 'paddleocr':
                from paddleocr import PaddleOCRVL, PPStructureV3
                if converter is None:
                    if args.variant == 'vlm':
                        converter = PaddleOCRVL(device='cpu', enable_mkldnn=False, cpu_threads=6, vl_rec_backend='llama-cpp-server',
                            vl_rec_server_url='http://127.0.0.1:8088/v1',
                            use_doc_orientation_classify=False, use_doc_unwarping=False)
                    else:
                        converter = PPStructureV3(device='cpu', enable_mkldnn=False, cpu_threads=6, use_doc_orientation_classify=False,
                                                  use_doc_unwarping=False)
                count = 0
                for number in case['pages']:
                    for result in converter.predict(str(BASE / 'runs/pages' / f'{sid}-p{number}.png')):
                        result.save_to_json(str(target))
                        result.save_to_markdown(str(target))
                        count += 1
                row.update(pages=count, version=importlib.metadata.version('paddleocr'))
            row['status'] = 'ok' if row.get('conversion_status', 'success') == 'success' else row['conversion_status']
        except Exception as error:
            row.update(status='failed', error=clean(f'{type(error).__name__}: {error}'))
            (target / 'error.txt').write_text(clean(traceback.format_exc()), encoding='utf-8')
        row['seconds'] = round(time.perf_counter() - started, 3)
        rows.append(row)
        save(target / 'status.json', row)
        save(output / 'run.json', rows)
        print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
