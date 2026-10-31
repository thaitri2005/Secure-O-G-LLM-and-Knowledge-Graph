"""Pinned OCRmyPDF prepass for English scanned pages."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from .runtime import BASE, digest, read, write


def prepass(source: Path, page: int, directory: Path) -> tuple[Path, dict]:
    from pypdf import PdfReader, PdfWriter
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'text.pdf'
    status = directory / 'engine.json'
    if not (target.is_file() and status.is_file()):
        writer = PdfWriter()
        writer.add_page(PdfReader(source).pages[page - 1])
        writer.write(directory / 'source.pdf')
        environment = os.environ.copy()
        environment['PYTHONPATH'] = str(BASE / 'src')
        environment['PATH'] = str(BASE / '.cache/tesseract') + os.pathsep + environment['PATH']
        environment['TESSDATA_PREFIX'] = str(BASE / '.cache/tesseract/tessdata')
        command = [str(BASE / '.venvs/ocrmypdf/Scripts/python.exe'), '-B', '-m',
                   'ingest_prototype.ocr', str(directory)]
        completed = subprocess.run(command, env=environment, capture_output=True, text=True,
                                   encoding='utf-8', errors='replace', timeout=600)
        (directory / 'ocr.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
        if completed.returncode:
            raise RuntimeError('OCR prepass failed; see the page-local ocr.log')
    return target, read(status)


def worker(directory: Path) -> None:
    import importlib.metadata
    import ocrmypdf
    ocrmypdf.ocr(str(directory / 'source.pdf'), str(directory / 'text.pdf'),
                language=['eng'], force_ocr=True, deskew=True, rotate_pages=True,
                optimize=0, output_type='pdf', progress_bar=False, jobs=1,
                sidecar=str(directory / 'sidecar.txt'))
    version = subprocess.check_output([str(BASE / '.cache/tesseract/tesseract.exe'), '--version'],
                                      text=True).splitlines()[0]
    write(directory / 'engine.json', {'engine': 'ocrmypdf',
        'version': importlib.metadata.version('ocrmypdf'), 'tesseract': version,
        'tesseract_sha256': digest(BASE / '.cache/tesseract/tesseract.exe'),
        'english_data_sha256': digest(BASE / '.cache/tesseract/tessdata/eng.traineddata'),
        'settings': {'language': ['eng'], 'force_ocr': True, 'deskew': True,
                     'rotate_pages': True, 'optimize': 0}, 'conversion_mode': 'text',
        'analysis_override': 'Use the prepassed text layer even when analysis reports hidden_text_layer.'})


if __name__ == '__main__':
    worker(Path(sys.argv[1]))
