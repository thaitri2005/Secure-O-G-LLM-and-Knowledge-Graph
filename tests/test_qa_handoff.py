import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from graph_builder.corpus.__main__ import main
from graph_builder.corpus.qa.handoff import MANIFEST, VIEW, read_verified_view, seal_view
from graph_builder.corpus.store import atomic_write_jsonl, file_sha256
from graphrag import data as graphrag_data


class HandoffTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.release = self.root / "release"
        self.release.mkdir()
        self.out = self.root / "qa"
        self.canonical = self.release / "chunks.jsonl"
        self.row = {"chunk_id": "c1", "doc_id": "well-dailyreport", "page": 1, "type": "text", "text": "Printed value"}
        atomic_write_jsonl(self.canonical, [self.row])
        self.checksum = f"{file_sha256(self.canonical)}  chunks.jsonl\n"
        (self.release / "SHA256SUMS").write_text(self.checksum, encoding="utf-8")
        (self.release / "manifest.json").write_text(json.dumps({"config": {"k1": {}}}), encoding="utf-8")
        self.view = self.out / VIEW

    def publish_view(self):
        self.note = {"r": 2, "c": 1, "reason": "numeric_cell_geometry_ambiguous"}
        atomic_write_jsonl(self.view, [dict(self.row, text="[unverified: 2 6]", numeric_review=[self.note])])
        seal_view(self.release, self.view, 1)

    @unittest.skipUnless(hasattr(graphrag_data, "load_k1_retrieval_chunks"),
                         "GraphRAG K1 retrieval handoff reader is unavailable")
    def test_consumer_checks_both_release_and_view_and_preserves_review(self):
        self.publish_view()
        with patch.dict("os.environ", {"GRAPHRAG_K1_CHUNKS": str(self.canonical), "GRAPHRAG_K1_RETRIEVAL_CHUNKS": str(self.view)}):
            chunk, = graphrag_data.load_k1_retrieval_chunks()
            self.assertEqual(chunk.numeric_review, (self.note,))
            self.assertIn("unverified", chunk.text)

    def test_view_checksums_bind_the_release_and_view(self):
        self.publish_view()
        sums = self.release / "SHA256SUMS"
        sums.write_text(self.checksum + "different release\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "different K1 release"):
            read_verified_view(self.canonical, self.view)
        sums.write_text(self.checksum, encoding="utf-8")
        self.view.write_text("changed view\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "view checksum"):
            read_verified_view(self.canonical, self.view)
        self.publish_view()
        self.canonical.write_text("changed K1 chunks\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "K1 chunks checksum"):
            read_verified_view(self.canonical, self.view)

    def test_failed_or_release_only_run_withdraws_the_previous_view(self):
        command = ["qa", "--release", str(self.release), "--out", str(self.out)]
        self.publish_view()
        with patch("graph_builder.corpus.qa.cli.build_qa", return_value={"validator": "fail", "signals": {}}):
            self.assertEqual(main(command), 1)
        self.assertFalse(self.view.exists())
        self.assertFalse((self.out / MANIFEST).exists())
        self.publish_view()
        with patch("graph_builder.corpus.qa.cli.build_qa", return_value={"validator": "pass", "signals": {}}):
            self.assertEqual(main(command), 1)
            self.assertEqual(main([*command, "--release-only"]), 0)
        self.assertFalse(self.view.exists())
        self.assertFalse((self.out / MANIFEST).exists())
