"""Re-chunk available document caches and compare their combined bytes with the documented deliverable digest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest

from docling_core.types.doc import DoclingDocument

from graph_builder.ingestion.chunking import chunks_from_document
from graph_builder.ingestion.sources import load_options, load_registry

ROOT = Path(__file__).resolve().parents[1]


class RegressionTests(unittest.TestCase):
    def test_cached_documents_match_documented_sha256(self) -> None:
        registry = load_registry(ROOT / "configs/sources/gdr_end_of_well.json")
        options = load_options(ROOT / "configs/ingestion/default.json")
        cache = ROOT / "data/interim/docling"
        if not all((cache / f"{source['doc_id']}.json").is_file() for source in registry):
            self.skipTest("Document caches are absent; run conversion to enable this regression check")
        records = []
        for source in registry:
            document = DoclingDocument.model_validate_json((cache / f"{source['doc_id']}.json").read_text(encoding="utf-8"))
            result, _ = chunks_from_document(document, source["doc_id"], options["max_chars"], options["margin_band"], options["frequency"],
                                              options["running_block_max_gap_lines"], options["running_block_alignment_lines"],
                                              options["running_line_fragment_gap_lines"])
            records.extend(result)
        payload = (json.dumps(records, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        expected = re.search(r"SHA256:\s*`([a-f0-9]{64})`", (ROOT / "docs/ingestion.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(expected)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), expected.group(1))
        self.assertEqual(payload, (ROOT / "data/processed/gdr_chunks.json").read_bytes())
