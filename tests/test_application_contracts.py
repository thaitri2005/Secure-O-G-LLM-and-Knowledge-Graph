"""Evidence, claim-revision and entity records: one corpus chunk and one dataset row share the same contract."""
from pathlib import Path
import tempfile
import unittest

from graph_builder.contracts import (ContractError, bundle_ref, claim_revision, entity, evidence_from_chunk,
                                     evidence_from_record)
from graph_builder.publication import publish

SHA = "a" * 64
DOCUMENT = {"doc_id": "gdr882_ak3_eowr", "sha256": SHA}
CHUNK = {"chunk_id": "gdr882_ak3_eowr#c00002", "doc_id": "gdr882_ak3_eowr", "type": "text", "page": 2, "pages": [2],
         "regions": [{"page": 2, "bbox": [72.0, 100.0, 540.0, 160.0]}], "table_id": None, "sha256": "b" * 64,
         "text": "Akutan Well AK-3 well was drilled to a vertical depth of 1,955 feet in 27 days."}
RECORD = {"record_id": "bsee_wells:borehole:012032016500", "table": "borehole", "total_md_ft": 21678,
          "source": {"dataset_id": "bsee_wells", "source_id": "borehole_gulf", "sha256": "c" * 64,
                     "member": "BoreholeRawData.txt", "row": 1}}


def release(base: Path, root: Path, content: str) -> dict:
    staging = Path(tempfile.mkdtemp(dir=base))
    (staging / "SHA256SUMS").write_text(content, encoding="utf-8")
    (staging / "manifest.json").write_text("{}", encoding="utf-8")
    publish(staging, root, "manifest.json", content.encode().hex().ljust(64, "0"))
    return bundle_ref(root, "corpus_export")


class ApplicationContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        self.bundle = release(self.base, self.base / "v1", "one")

    def tearDown(self):
        self.directory.cleanup()

    def test_document_evidence_pins_release_and_quote(self):
        quote = "vertical depth of 1,955 feet"
        evidence = evidence_from_chunk(CHUNK, DOCUMENT, self.bundle, quote)
        self.assertEqual(evidence["locator"]["quote_start"], CHUNK["text"].index(quote))
        self.assertEqual(evidence, evidence_from_chunk(CHUNK, DOCUMENT, self.bundle, quote))  # deterministic
        republished = release(self.base, self.base / "v1", "two")
        self.assertNotEqual(evidence["evidence_id"],
                            evidence_from_chunk(CHUNK, DOCUMENT, republished, quote)["evidence_id"])
        with self.assertRaisesRegex(ContractError, "not found verbatim"):
            evidence_from_chunk(CHUNK, DOCUMENT, self.bundle, "1,700 feet")

    def test_dataset_row_evidence_uses_the_same_record_shape(self):
        bundle = {**self.bundle, "kind": "dataset_release"}
        evidence = evidence_from_record(RECORD, bundle, ["total_md_ft"])
        self.assertEqual((evidence["kind"], evidence["locator"]["row"]), ("dataset_row", 1))
        self.assertEqual(evidence["source"]["source_id"], "bsee_wells/borehole_gulf")
        with self.assertRaisesRegex(ContractError, "no fields"):
            evidence_from_record(RECORD, bundle, ["tvd_ft"])

    def test_claim_revisions_change_with_value_or_evidence_but_not_resolution(self):
        evidence = evidence_from_chunk(CHUNK, DOCUMENT, self.bundle, "1,955 feet")["evidence_id"]
        subject = {"entity_type": "Well", "mention": "Akutan Well AK-3", "key": "AK3"}
        arguments = dict(profile="oil_wells@0.2", subject=subject, property_name="total_depth", qualifier="actual",
                         value={"raw": "1,955", "unit": "ft"}, context={}, evidence=[evidence],
                         origin={"method": "model_extraction", "version": "qwen2.5-3b extract-v5"})
        first = claim_revision(**arguments)
        corrected = claim_revision(**{**arguments, "value": {"raw": "1,995", "unit": "ft"}})
        self.assertEqual(first["claim_id"], corrected["claim_id"])
        self.assertNotEqual(first["revision_id"], corrected["revision_id"])
        well = entity("oil_wells@0.2", "Well", [{"text": "AK-3", "language": "en", "scope": "Akutan"}], key="AK3")
        resolved = claim_revision(**{**arguments, "subject": {**subject, "entity_id": well["entity_id"]}})
        self.assertEqual(first["revision_id"], resolved["revision_id"])
        with self.assertRaises(ContractError):
            claim_revision(**{**arguments, "evidence": []})

    def test_entity_ids_come_from_identifiers_first(self):
        names = [{"text": "OCS-G 1234 A-1", "language": "en", "scope": "OCS-G 1234"}]
        by_api = entity("oil_wells@0.2", "Wellbore", names, [{"scheme": "bsee_api12", "value": "012032016500"}])
        renamed = entity("oil_wells@0.2", "Wellbore", [{**names[0], "text": "A-1 ST"}],
                         [{"scheme": "bsee_api12", "value": "012032016500"}])
        self.assertEqual(by_api["entity_id"], renamed["entity_id"])  # names are never identity
        with self.assertRaises(ContractError):
            entity("oil_wells@0.2", "Well", names)


if __name__ == "__main__":
    unittest.main()
