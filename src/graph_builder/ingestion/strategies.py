"""Optional token-budget chunking using the installed document chunker."""
from functools import lru_cache
import os

from docling_core.types.doc import TableItem

from .filters import dropped_item_reasons, filter_running_lines
from .provenance import item_regions

from docling_core.transforms.chunker.hierarchical_chunker import ChunkingSerializerProvider, ChunkingDocSerializer
from docling_core.transforms.serializer.markdown import MarkdownTableSerializer, MarkdownParams


class PassageSerializerProvider(ChunkingSerializerProvider):
    def get_serializer(self, doc):
        return ChunkingDocSerializer(doc=doc, table_serializer=MarkdownTableSerializer(),
                                    params=MarkdownParams(image_placeholder="", escape_underscores=False,
                                                          escape_html=False, include_formatting=False,
                                                          include_hyperlinks=False, traverse_pictures=True))


@lru_cache(maxsize=1)
def hybrid_chunker():
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    from transformers import AutoTokenizer
    from docling_core.transforms.chunker import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
    tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
    return HybridChunker(tokenizer=HuggingFaceTokenizer(tokenizer=tokenizer, max_tokens=512), merge_peers=True,
                         serializer_provider=PassageSerializerProvider())


def hybrid_chunks(document, doc_id: str, options: dict, chunker=None) -> tuple[list[dict], list[dict]]:
    document, _ = filter_running_lines(document, options["margin_band"], options["frequency"],
                                       options["running_block_max_gap_lines"], options["running_block_alignment_lines"],
                                       options["running_line_fragment_gap_lines"])
    excluded = dropped_item_reasons(document)
    # Clear excluded content without deleting picture descendants with PDF text.
    for item in document.texts:
        if item.self_ref in excluded:
            item.text = ""
    for item in document.tables:
        if item.self_ref in excluded:
            for cell in item.data.table_cells:
                cell.text = ""
    chunks, metadata = [], []
    for chunk in (chunker or hybrid_chunker()).chunk(document):
        items = [item for item in chunk.meta.doc_items if item.self_ref not in excluded and item.prov]
        if not chunk.text.strip() or not items:
            continue
        headings = list(chunk.meta.headings or [])
        chunks.append({"doc_id": doc_id, "page": items[0].prov[0].page_no,
                       "chunk_id": f"{doc_id}#c{len(chunks):04d}",
                       "type": "table" if any(isinstance(item, TableItem) for item in items) else "text",
                       "text": chunk.text, "section": headings[-1] if headings else None})
        from .attribution import source_spans
        metadata.append({"regions": item_regions(document, [(item, None) for item in items]),
                         "source_spans": source_spans(document, chunk.text, [(item, None) for item in items]),
                         "section_path": headings, "table_id": None, "row_start": None, "row_end": None})
        tables = [item.get_ref().resolve(document) for item in items
                  if isinstance(item.get_ref().resolve(document), TableItem)]
        if tables:
            references = [{"table_id": f"{doc_id}#t{document.tables.index(table):03d}",
                           "row_start": 0, "row_end": table.data.num_rows} for table in tables]
            metadata[-1].update(**references[0], table_refs=references)
    return chunks, metadata
