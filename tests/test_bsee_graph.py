"""BSEE records become a linked graph whose edges cite their source rows."""
import json
from pathlib import Path
import tempfile
import unittest

from graph_builder.graph.bsee import block_key, build_graph, check_graph, neighbors
from graph_builder.ingestion.sources import write_text


def borehole(api: str, row: int, **values) -> dict:
    record = {"record_id": f"bsee:borehole:{api}", "api_well_number": api, "well_api10": api[:10],
              "well_name": "A001", "well_name_suffix": "ST00BP00", "region": "gulf_of_america", "status_code": "PA",
              "status_date": None, "type_code": "D", "well_class_code": "DIR", "spud_date": None,
              "total_depth_date": None, "bh_total_md_ft": 1000, "tvd_ft": 900, "rkb_elevation_ft": 90,
              "water_depth_ft": 50, "surface_latitude": 28.0, "surface_longitude": -90.0, "coordinate_datum": "NAD27",
              "withheld": [], "operator_number": "00276", "surface_lease_number": "G01608",
              "bottom_lease_number": "G01608", "surface_area_code": "SP", "surface_block_number": "0060",
              "bottom_area_code": "SP", "bottom_block_number": "0061", "bottom_field_name_code": "SP060",
              "source": {"file_id": "borehole_gulf", "sha256": "a" * 64, "row": row}}
    return {**record, **values}


class GraphTests(unittest.TestCase):
    def test_links_cite_rows_and_skip_placeholders(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            records = [borehole("177214004100", 1), borehole("177214004101", 2, bottom_field_name_code="WILD"),
                       borehole("177214009900", 3, surface_lease_number="NOLEASE")]
            change = {"record_id": "bsee:api_changes_gulf:1", "api_well_number": "177214004101",
                      "previous_api_number": "17-721-40099-00", "source": {"file_id": "api_changes_gulf",
                                                                          "sha256": "b" * 64, "row": 1}}
            write_text(bundle / "boreholes.jsonl", "".join(json.dumps(r) + "\n" for r in records))
            write_text(bundle / "api_changes.jsonl", json.dumps(change) + "\n")
            nodes, edges, skipped = build_graph(bundle)
            self.assertEqual(check_graph(nodes, edges), [])
            self.assertEqual(skipped, {"field placeholder": 1, "surface_lease placeholder": 1})
            well = neighbors(nodes, edges, "well:1772140041")
            self.assertEqual(well["links"]["HAS_WELLBORE ->"]["count"], 2)
            self.assertNotIn("field:WILD", nodes)
            self.assertIn("block:SP-60", nodes)
            renumbered = [e for e in edges if e["relation"] == "RENUMBERED_FROM"]
            self.assertEqual([(e["source"], e["target"]) for e in renumbered],
                             [("wellbore:177214004101", "wellbore:177214009900")])
            self.assertEqual(renumbered[0]["evidence"]["row"], 1)
            self.assertEqual(neighbors(nodes, edges, "lease:G01608")["links"]["<- SURFACE_ON_LEASE"]["count"], 2)
            with self.assertRaisesRegex(ValueError, "Unknown node"):
                neighbors(nodes, edges, "well:0")

    def test_block_keys_ignore_zero_padding(self):
        self.assertEqual(block_key("MO", "0827"), block_key("MO", "827"))
        self.assertEqual(block_key("EI", "0128A"), "EI-128A")
        self.assertIsNone(block_key("MO", None))
