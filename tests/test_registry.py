"""Registry built from a dataset release, and conservative resolution (FR-05, FR-16)."""
import json
from pathlib import Path
import tempfile
import unittest

from graph_builder.datasets.importer import run_import
from graph_builder.datasets.mapping import validate_mapping
from graph_builder.registry import Registry, build

# Two wellbores share the name "001" on different leases. A-2 lists a previous number that is not in the file,
# so the importer makes no RENUMBERED_FROM edge for it (require_existing).
BOREHOLES = ("api,api10,name,lease,previous\n"
             "012032016500,0120320165,001,G01234,\n"
             "012032016600,0120320166,001,G05678,\n"
             "012032016700,0120320167,A-2,G01234,012032099900\n")


def mapping(base: Path) -> dict:
    value = {
        "dataset_id": "wells", "title": "Wells", "license": {"id": "test", "url": ""},
        "sources": [{"source_id": "b", "table": "borehole", "path": "boreholes.csv"}],
        "tables": {"borehole": {"layout": {"type": "csv"}, "id": "wells:{api}", "key": ["api"],
                                "columns": [{"name": "api", "type": "string"}, {"name": "api10", "type": "string"},
                                            {"name": "name", "type": "string"}, {"name": "lease", "type": "string"},
                                            {"name": "previous", "type": "string"}]}},
        "graph": {"nodes": [{"label": "Wellbore", "table": "borehole", "id": "wellbore:{api}",
                             "properties": {"api_well_number": "api", "well_name": "name"}},
                            {"label": "Well", "table": "borehole", "id": "well:{api10}", "properties": ["api10"]},
                            {"label": "Lease", "table": "borehole", "id": "lease:{lease}",
                             "properties": {"lease_number": "lease"}}],
                  "edges": [{"type": "SURFACE_ON_LEASE", "table": "borehole", "from": "wellbore:{api}",
                             "to": "lease:{lease}"},
                            {"type": "RENUMBERED_FROM", "table": "borehole", "from": "wellbore:{api}",
                             "to": "wellbore:{previous}", "require_existing": True}]},
        "_base": str(base)}
    validate_mapping(value)
    return value


class RegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        base = Path(cls.directory.name)
        (base / "boreholes.csv").write_text(BOREHOLES, encoding="utf-8")
        run_import(mapping(base), base, base / "dataset")
        config = json.loads(Path("configs/registry/bsee_wells.registry.json").read_text(encoding="utf-8"))
        config.update(dataset="dataset", output="registry")
        cls.summary = build(config, base)
        cls.registry = Registry.load(base / "registry")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_build_counts(self):
        self.assertEqual(self.summary["counts"]["Wellbore"], 3)
        self.assertEqual(self.summary["counts"]["Well"], 3)

    def test_identifiers_resolve_in_any_spelling(self):
        result = self.registry.resolve("API 01-203-20165-00")
        self.assertEqual((result["status"], result["via"], result["scheme"]), ("resolved", "identifier", "bsee_api12"))
        self.assertEqual(self.registry.resolve("0120320165")["scheme"], "bsee_api10")

    def test_a_name_needs_a_scope(self):
        unscoped = self.registry.resolve("001", "Wellbore")
        self.assertEqual(unscoped["status"], "needs_review")
        self.assertEqual(len(unscoped["candidates"]), 2)
        scoped = self.registry.resolve("001", "Wellbore", scope="G-05678")
        self.assertEqual((scoped["status"], scoped["via"]), ("resolved", "scoped_name"))
        self.assertEqual(scoped["entity_id"], self.registry.resolve("012032016600")["entity_id"])
        self.assertEqual(self.registry.resolve("a 2", "Wellbore")["status"], "needs_review")  # one match, still review
        self.assertEqual(self.registry.resolve("001", "Wellbore", scope="G09999")["status"], "unknown")

    def test_former_identifiers_resolve_to_the_current_entity(self):
        with tempfile.TemporaryDirectory() as folder:
            release = Path(folder)
            item = {"entity_id": "ent:" + "1" * 24, "entity_type": "Wellbore", "profile": "oil_wells@0.2",
                    "identifiers": [{"scheme": "bsee_api12", "value": "012032016700"}],
                    "former_identifiers": [{"scheme": "bsee_api12", "value": "012032099900"}],
                    "names": [{"text": "A-2", "language": "en", "scope": "G01234"}]}
            (release / "entities.jsonl").write_text(json.dumps(item) + "\n", encoding="utf-8")
            (release / "summary.json").write_text(json.dumps(
                {"schemes": {"bsee_api12": {"strip": "non_digits", "length": 12}}}), encoding="utf-8")
            result = Registry(release).resolve("012032099900")
        self.assertEqual((result["status"], result["via"], result["entity_id"]),
                         ("resolved", "former_identifier", item["entity_id"]))

    def test_unknown_mentions_stay_unknown(self):
        self.assertEqual(self.registry.resolve("AK-3")["status"], "unknown")
        self.assertEqual(self.registry.resolve("999999999999")["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
