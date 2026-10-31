"""Segment conversion with a common JSON validation boundary."""
from __future__ import annotations

import gzip
from pathlib import Path
import time
from typing import Any

from .runtime import read, write

_CONVERTERS: dict[tuple, Any] = {}


def segment(source: Path, mode: str, pages: tuple[int, int] | None, cache: Path,
            config: dict) -> tuple[Any, dict]:
    """Return the same revalidated representation on fresh and cached paths."""
    from docling_core.types.doc import DoclingDocument
    from graph_builder.corpus.convert import build_converter
    metadata = cache.with_suffix('.meta.json')
    reused = cache.is_file() and metadata.is_file()
    if not reused:
        key = (mode, str(config))
        if key not in _CONVERTERS:
            from .runtime import BASE
            _CONVERTERS[key] = build_converter(config, BASE / 'models/corpus-ocr',
                                              {'text': None, 'hybrid': False, 'ocr': True}[mode])
        started = time.perf_counter()
        result = _CONVERTERS[key].convert(source, raises_on_error=False,
                                         **({'page_range': pages} if pages else {}))
        if result.status.value not in ('success', 'partial_success'):
            raise RuntimeError(f'Conversion failed: {result.status.value}: {result.errors}')
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_name(cache.name + '.partial')
        with gzip.open(temporary, 'wt', encoding='utf-8') as stream:
            stream.write(result.document.model_dump_json())
        temporary.replace(cache)
        write(metadata, {'seconds': round(time.perf_counter() - started, 3),
                         'status': result.status.value, 'mode': mode, 'pages': pages})
    with gzip.open(cache, 'rt', encoding='utf-8') as stream:
        document = DoclingDocument.model_validate_json(stream.read())
    return document, dict(read(metadata), cached=reused)
