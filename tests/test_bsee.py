"""BSEE well files are verified, parsed with their published layouts and checked across records."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from graph_builder.ingestion.bsee import fetch_dataset, load_dataset, parse_dataset, validate_outputs, write_outputs
from graph_builder.ingestion.bsee_layouts import BOREHOLE, parse_row
from graph_builder.ingestion.sources import write_json

BASE = "https://www.data.bsee.gov/Well/Files/"
ORIGINAL = ('"012032016500","  001 ","ST00BP00","00276","WILD    ","19840924","S00538    ","00099","21678","21675",'
            '"03707N07080W","MO 0827 ","03580N07118W","MO 0827 ","19850310","19930309","E","01","COM","00045",'
            '"      -87.958630","       30.188450","      -87.958515","       30.188800","S00538    ","2134   ","1 ",'
            '"20191216","STR"')
SIDETRACK = ORIGINAL.replace("012032016500", "012032016501").replace("ST00BP00", "ST01BP00").replace('"  001 "', '"  002 "')
WITHHELD = ('"177034089400","  A012","ST00BP00","02628","EI330   ","20250102","G09372    ","00100","#####","#####",'
            '"01201N02073E","EI 0330 ","############","EI 0330 ","        ","20250301","D","03","DRL","00210",'
            '"      -91.500379","       28.971751","################","################","G09372    ","23874  ","1 ",'
            '"        ","###"')
CHANGE = ('"012032016501","API","01-203-20165-99","07/12/1995","  002","ST01BP00","S00538","MO","  827","09/24/1984",'
          '"S00538","MO","  827","*****"')


def archive(member: str, lines: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as stream:
        stream.writestr(member, "".join(line + "\r\n" for line in lines))
    return buffer.getvalue()


class Response(io.BytesIO):
    headers = {"Last-Modified": "Sun, 18 Oct 2026 12:57:43 GMT"}


def make_config(root: Path, files: list[dict]) -> dict:
    path = root / "configs/datasets/wells.json"
    write_json(path, {"dataset_id": "wells", "title": "Wells", "landing_page": "https://www.data.bsee.gov/Main/Well.aspx",
                      "license": {"id": "BSEE-disclaimer", "url": "https://www.bsee.gov/"}, "files": files})
    return load_dataset(path)


def borehole_file(file_id: str = "boreholes", **extra) -> dict:
    return {"file_id": file_id, "table": "borehole", "region": "gulf_of_america", "datum": "NAD27",
            "url": BASE + f"{file_id}.zip", "member": "5010.txt", **extra}


CHANGE_FILE = {"file_id": "changes", "table": "api_change", "region": "gulf_of_america",
               "url": BASE + "changes.zip", "member": "apichg.txt"}


class LayoutTests(unittest.TestCase):
    def test_padded_and_combined_columns_become_typed_fields(self):
        values, withheld = parse_row(BOREHOLE, next(csv.reader([ORIGINAL])))
        self.assertEqual(withheld, [])
        self.assertEqual(values["well_name"], "001")
        self.assertEqual(values["spud_date"], "1984-09-24")
        self.assertEqual((values["bh_total_md_ft"], values["tvd_ft"], values["water_depth_ft"]), (21678, 21675, 45))
        self.assertEqual((values["surface_ns_distance"], values["surface_ns_code"], values["surface_ew_distance"],
                          values["surface_ew_code"]), (3707, "N", 7080, "W"))
        self.assertEqual((values["surface_area_code"], values["surface_block_number"]), ("MO", "0827"))
        self.assertEqual(values["surface_latitude"], 30.18845)

    def test_withheld_values_differ_from_blank_values(self):
        values, withheld = parse_row(BOREHOLE, next(csv.reader([WITHHELD])))
        self.assertIn("tvd_ft", withheld)
        self.assertIn("bottom_ew_code", withheld)
        self.assertNotIn("total_depth_date", withheld)
        self.assertIsNone(values["tvd_ft"])
        self.assertIsNone(values["total_depth_date"])

    def test_malformed_rows_are_rejected(self):
        row = next(csv.reader([ORIGINAL]))
        for index, value, message in ((0, "12345", "12 digits"), (5, "19841324", "date"), (5, "1984111", "date"),
                                      (8, "2l678", "integer"), (10, "03707N0708W", "width")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, message):
                    parse_row(BOREHOLE, row[:index] + [value] + row[index + 1:])
        with self.assertRaisesRegex(ValueError, "columns"):
            parse_row(BOREHOLE, row[:-1])


class DatasetTests(unittest.TestCase):
    def serve(self, payloads: dict[str, bytes]):
        return patch("graph_builder.ingestion.bsee.open_https", side_effect=lambda url, host: Response(payloads[url]))

    def test_bundle_is_verified_deterministic_and_tamper_evident(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = make_config(root, [borehole_file(), CHANGE_FILE])
            payloads = {BASE + "boreholes.zip": archive("5010.txt", [ORIGINAL, SIDETRACK, WITHHELD]),
                        BASE + "changes.zip": archive("apichg.txt", [CHANGE])}
            with self.serve(payloads) as network:
                self.assertFalse(any(result["cached"] for result in fetch_dataset(config, root)))
                self.assertTrue(all(result["cached"] for result in fetch_dataset(config, root)))
                self.assertEqual(network.call_count, 2)
            records, errors, warnings = parse_dataset(config, root)
            self.assertEqual(errors.counts, {})
            self.assertEqual(warnings.counts["withheld_fields"], 1)
            output = root / "data/processed/local/wells"
            write_outputs(config, root, output, records, warnings)
            self.assertEqual(validate_outputs(output), [])
            first = {path.name: path.read_bytes() for path in output.iterdir()}
            records, _, warnings = parse_dataset(config, root)
            write_outputs(config, root, output, records, warnings)
            self.assertEqual(first, {path.name: path.read_bytes() for path in output.iterdir()})

            wells = [json.loads(line) for line in (output / "wells.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([well["well_api10"] for well in wells], ["0120320165", "1770340894"])
            self.assertEqual([b["api_well_number"] for b in wells[0]["boreholes"]], ["012032016500", "012032016501"])
            self.assertEqual(wells[0]["previous_api_numbers"], ["01-203-20165-99"])
            change = json.loads((output / "api_changes.jsonl").read_text(encoding="utf-8"))
            self.assertEqual((change["activity_date"], change["withheld"]), ("1995-07-12", ["bh_total_md_ft"]))
            self.assertEqual(change["source"]["row"], 1)

            (output / "boreholes.jsonl").write_text("{}\n", encoding="utf-8")
            self.assertTrue(any("SHA256" in error for error in validate_outputs(output)))
            (root / "data/raw/wells/boreholes.zip").write_bytes(archive("5010.txt", [ORIGINAL]))
            with self.assertRaisesRegex(ValueError, "snapshot"):
                fetch_dataset(config, root)

    def test_pins_hosts_and_foreign_directories_are_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "www.data.bsee.gov"):
                make_config(root, [borehole_file(url="https://example.com/5010.zip")])
            with self.assertRaisesRegex(ValueError, "datum"):
                make_config(root, [borehole_file(datum=None)])
            config = make_config(root, [borehole_file(sha256="0" * 64)])
            with self.serve({BASE + "boreholes.zip": archive("5010.txt", [ORIGINAL])}):
                with self.assertRaisesRegex(ValueError, "pinned"):
                    fetch_dataset(config, root)
            self.assertFalse((root / "data/raw/wells/boreholes.zip").exists())
            config = make_config(root, [borehole_file()])
            with self.serve({BASE + "boreholes.zip": archive("5010.txt", [ORIGINAL])}):
                fetch_dataset(config, root)
            records, _, warnings = parse_dataset(config, root)
            (root / "elsewhere").mkdir()
            (root / "elsewhere/notes.txt").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Refusing"):
                write_outputs(config, root, root / "elsewhere", records, warnings)
            self.assertTrue((root / "elsewhere/notes.txt").exists())

    def test_duplicate_boreholes_across_files_are_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = make_config(root, [borehole_file("first"), borehole_file("second")])
            with self.serve({BASE + "first.zip": archive("5010.txt", [ORIGINAL]),
                             BASE + "second.zip": archive("5010.txt", [ORIGINAL])}):
                fetch_dataset(config, root)
            _, errors, _ = parse_dataset(config, root)
            self.assertEqual(errors.counts["duplicate_api_well_number"], 1)
