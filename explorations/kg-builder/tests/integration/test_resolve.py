"""SemHash and alias-rule resolution tests on showcase surfaces."""
from __future__ import annotations
import unittest
import socket
from unittest.mock import patch
from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.core.config import load_config
from kgbuilder.core.contracts import Mention
from kgbuilder.build.ingest.corpus import load_corpus
from kgbuilder.build.refine.resolve import base_key, is_literal, resolve
from kgbuilder.runtime.onprem import load_env, guard_network, blocked_count


class ResolveTest(unittest.TestCase):
    def setUp(self):
        load_env()
        self.tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/resolve" / self._testMethodName)
        self.saved = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
        guard_network(self.tmp / "net.jsonl")
        self.cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml")
        self.docs = load_corpus(self.cfg)
        self.texts = [d.text for d in self.docs]
        surfaces = []
        import json
        kg = json.loads((PROJECT_ROOT / "results/upstream/kggen/showcase/kg_merged.json").read_text(encoding="utf-8"))
        surfaces = sorted(set(x for triple in kg["relations"] for x in (triple[0], triple[2])))
        self.surfaces = surfaces + ["1964", "1965"]

    def tearDown(self):
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = self.saved
        self.assertEqual(blocked_count(self.tmp / "net.jsonl"), 0)

    def test_literals_and_base(self):
        self.assertTrue(is_literal("1964")); self.assertTrue(is_literal("2024-10"))
        self.assertFalse(is_literal("IBM"))
        self.assertEqual(base_key("International Business Machines Corporation"), "international business machines")
        self.assertEqual(base_key("Acme Labs"), "acme labs")

    def test_showcase_resolution(self):
        mentions = [Mention(mention_id=f"m{i}", chunk_id="d#c000", surface=s, char_start=None, char_end=None, extractor_version="v") for i, s in enumerate(self.surfaces)]
        result = resolve(self.surfaces, mentions, self.texts, self.cfg, True)
        ibm = next(e for e in result.entities if e.name == "IBM")
        self.assertTrue({"International Business Machines", "International Business Machines Corporation"} <= set(ibm.aliases))
        self.assertNotEqual(result.by_key["ibm research"], ibm.entity_id)
        self.assertNotEqual(result.by_key["1964"], result.by_key["1965"])
        self.assertEqual(result.surfaces_non_literal, len([x for x in self.surfaces if not is_literal(x)]))

    def test_ambiguous_acronym(self):
        surfaces = ["ABC", "Alpha Beta Company", "Another Better Company"]
        mentions = [Mention(mention_id=f"m{i}", chunk_id="d#c000", surface=s, char_start=None, char_end=None, extractor_version="v") for i, s in enumerate(surfaces)]
        result = resolve(surfaces, mentions, ["ABC Alpha Beta Company Another Better Company"], self.cfg, True)
        self.assertGreaterEqual(result.ambiguous_acronyms, 1)
        self.assertNotEqual(result.by_key["abc"], result.by_key["alpha beta company"])

    def test_collision_suffix(self):
        with patch("kgbuilder.build.refine.resolve.h", return_value="samehash"):
            result = resolve(["1964", "1965"], [], [], self.cfg, False)
        self.assertEqual([e.entity_id for e in result.entities], ["e_samehash", "e_samehash_2"])

    def test_frequency_and_identity_first(self):
        result = resolve(["Acme Inc", "Acme"], [], ["Acme Inc Acme Inc"], self.cfg, True)
        self.assertEqual(result.entities[0].name, "Acme")
        identity = resolve(["ibm", "IBM"], [], ["IBM IBM"], self.cfg, False)
        self.assertEqual(identity.entities[0].name, "ibm")

    def test_identity(self):
        surfaces = ["IBM", "IBM", "Acme"]
        mentions = [Mention(mention_id="m1", chunk_id="d#c000", surface="IBM", char_start=None, char_end=None, extractor_version="v")]
        result = resolve(surfaces, mentions, ["IBM Acme"], self.cfg, False)
        self.assertEqual(len(result.entities), 2)
        self.assertTrue(all(e.resolver == "identity" for e in result.entities))

    def test_number_guard(self):
        surfaces = [f"{n} Earl of Strathmore and Kinghorne" for n in ("3rd", "4th", "6th", "8th")] + ["Cnut", "Cnut the Great"]
        cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", sets=["resolve.number_guard=true"])
        result = resolve(surfaces, [], [], cfg, True)
        self.assertEqual(len({result.by_key[s.lower()] for s in surfaces[:4]}), 4)
        self.assertEqual(result.by_key["cnut"], result.by_key["cnut the great"])


if __name__ == "__main__":
    unittest.main()
