"""Synthetic streaming bundles, source integrity, quarantines and deterministic bytes."""
from __future__ import annotations

import csv
import io
import json
import unittest
import zipfile
from unittest.mock import patch

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.build.ingest.bsee_tables import build_tables, iter_table
from kgbuilder.core.config import ConfigError, DomainTablesConfig
from kgbuilder.core.domain import verify_bundle
from kgbuilder.core.text import cj, read_jsonl, sha256_file, sha256_text, write_json


def table_fixture(root):
    cases = json.loads((PROJECT_ROOT / "tests/fixtures/bsee/tables.json").read_text())
    files = {}
    def archive(name, member, columns, rows, region=None):
        path = root / name
        content = io.StringIO(newline="")
        writer = csv.writer(content)
        writer.writerow(columns)
        writer.writerows(rows)
        with zipfile.ZipFile(path, "w") as z: z.writestr(member, content.getvalue())
        allowed = [c for c in columns if c != "CONTACT_NAME"]
        files[name] = {"path": path.relative_to(PROJECT_ROOT).as_posix(), "sha256": sha256_file(path), "region": region,
                       "members": {member: {"header": columns, "encoding": "utf-8", "allow_columns": allowed,
                                           "deny_columns": ["CONTACT_NAME"], "verified_by": "dictionary_tokens"}}}
    archive("5010delimit.zip", "5010.txt", ["API_WELL_NUMBER", "BOTM_LEASE_NUMBER"], cases["boreholes"], "gom")
    archive("5010pacdelimit.zip", "5010.txt", ["API_WELL_NUMBER", "BOTM_LEASE_NUMBER"], [["012345679100", "00127"]], "pacific")
    archive("5010akdelimit.zip", "5010.txt", ["API_WELL_NUMBER", "BOTM_LEASE_NUMBER"], [["012345679200", "A00001"]], "alaska")
    archive("compalldelimit.zip", "compalldelimit.txt", ["MMS_COMPANY_NUM", "BUS_ASC_NAME", "CONTACT_NAME"],
            [row + ["SYNTHETIC_DENY_SENTINEL"] for row in cases["companies"]])
    archive("lseowndelimit.zip", "lseowndelimit.txt", ["LEASE_NUMBER", "MMS_COMPANY_NUM", "ASSIGNMENT_PCT"], cases["ownership"])
    archive("apichgdelimit.zip", "apichgdelimit.txt", ["PREV_API_NUMBER", "API_WELL_NUMBER", "ACTIVITY_DATE"], [["012345678900", "012345678901", "1/2/2020"]])
    archive("eWellEORRawData.zip", "eWellEORRawData/mv_eor_mainquery.txt", ["SN_EOR", "API_WELL_NUMBER", "EOR_OPERATION_CD", "OPERATIONAL_NARRATIVE"], cases["reports"])
    path = root / "manifest.json"
    data = {"format": "kgb.bsee_sources/1", "snapshot": "synthetic", "files": files, "not_mapped": [], "attribution": "synthetic"}
    data["data_sha256"] = sha256_text(cj(data))
    write_json(path, data)
    return DomainTablesConfig(source_manifest=path, regions=["gom", "pacific", "alaska"], scope="extended")


class BseeTablesTest(unittest.TestCase):
    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/bsee_tables")
        self.cfg = table_fixture(self.root)
        self.output = clean_dir(PROJECT_ROOT / "runs/_test/bsee_tables")

    def test_counts_quarantine_provenance_and_repeat(self):
        first = self.output / "first"; first.mkdir()
        second = self.output / "second"; second.mkdir()
        stats = build_tables(self.cfg, first)
        again = build_tables(self.cfg, second)
        self.assertEqual(verify_bundle(first).files, verify_bundle(second).files)
        self.assertEqual(stats["boreholes_by_region"], {"gom": 3, "pacific": 1, "alaska": 1})
        self.assertEqual(stats["lease_region_collision"], 4)
        self.assertEqual(stats["tables"]["mv_eor_mainquery"]["quarantined"], 2)
        self.assertEqual(stats["joins"]["eor_borehole"], {"numerator": 1, "denominator": 2})
        nodes = read_jsonl(first / "nodes.jsonl")
        company = next(n for n in nodes if n["id"] == "bsee:company:00001")
        self.assertEqual(len(company["sources"]), 2)
        self.assertFalse(any(n["id"] == "bsee:lease:00127" for n in nodes))
        self.assertFalse(any(n["id"] == "bsee:eor:-2" for n in nodes))
        for path in first.glob("*.jsonl"):
            raw = path.read_text()
            self.assertNotIn("SYNTHETIC_DENY_SENTINEL", raw)
            self.assertNotIn("Synthetic narrative for table", raw)
        self.assertEqual(stats["llm_calls"], 0)

    def test_tampered_source_and_denylist(self):
        path = self.root / "compalldelimit.zip"
        path.write_bytes(path.read_bytes() + b"tamper")
        with self.assertRaisesRegex(ConfigError, "hash mismatch"):
            list(iter_table(self.cfg.source_manifest, "compalldelimit.zip", "compalldelimit.txt"))

    def test_headered_location_provenance(self):
        data = json.loads(self.cfg.source_manifest.read_text())
        name, member = "BoreholeRawData.zip", "BoreholeRawData/mv_boreholes_all.txt"
        path = self.root / name
        header = ["API_WELL_NUMBER", "BOTM_AREA_CODE", "BOTM_BLOCK_NUMBER"]
        stream = io.StringIO(newline="")
        writer = csv.writer(stream); writer.writerow(header); writer.writerow(["012345678900", "SY", "001"])
        with zipfile.ZipFile(path, "w") as z: z.writestr(member, stream.getvalue())
        data["files"][name] = {"path": path.relative_to(PROJECT_ROOT).as_posix(), "sha256": sha256_file(path),
                               "members": {member: {"header": header, "encoding": "utf-8", "allow_columns": header, "verified_by": "dictionary_tokens"}}}
        data["data_sha256"] = sha256_text(cj({k: v for k, v in data.items() if k != "data_sha256"}))
        write_json(self.cfg.source_manifest, data)
        build_tables(self.cfg, self.output)
        locations = [n for n in read_jsonl(self.output / "nodes.jsonl") if n["type"] in {"Area", "Block"}]
        self.assertEqual(len(locations), 2)
        for node in locations:
            self.assertTrue(all("BOTM_AREA_CODE" in source["fields"] and source["member"] == member for source in node["sources"]))
        links = [e for e in read_jsonl(self.output / "edges.jsonl") if e["type"] == "BOTTOM_IN_BLOCK"]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["sources"][0]["member"], member)

    def test_streaming_allowlist_and_raw_hash(self):
        rows = list(iter_table(self.cfg.source_manifest, "compalldelimit.zip", "compalldelimit.txt"))
        self.assertNotIn("CONTACT_NAME", rows[0]["values"])
        self.assertEqual(rows[0]["record_no"], 1)
        self.assertEqual(len(rows[0]["raw_row_sha256"]), 64)

    def test_child_report_join_and_typed_observations(self):
        data = json.loads(self.cfg.source_manifest.read_text())
        entry = data["files"]["eWellEORRawData.zip"]
        path = PROJECT_ROOT / entry["path"]
        members = {
            "mv_eor_mainquery_prop": (["SN_EOR", "BH_TOTAL_MD", "WELL_BORE_TVD"], [["-1", "12000", "11000"]]),
            "mv_eor_completions": (["SN_EOR_FK", "SN_EOR_WELL_COMP"], [["-1", "-10"]]),
            "mv_eor_perf_intervals": (["SN_EOR_WELL_COMP_FK", "PERF_TOP_MD", "PERF_BASE_MD"], [["-10", "5000", "5100"], ["-99", "100", "200"]]),
        }
        with zipfile.ZipFile(path, "a") as z:
            for name, (columns, rows) in members.items():
                stream = io.StringIO(newline="")
                writer = csv.writer(stream); writer.writerow(columns); writer.writerows(rows)
                member = "eWellEORRawData/" + name + ".txt"
                z.writestr(member, stream.getvalue())
                entry["members"][member] = {"header": columns, "encoding": "utf-8", "allow_columns": columns,
                                             "verified_by": {c: "raw_header+rawdata_page" for c in columns}}
        entry["sha256"] = sha256_file(path)
        data["data_sha256"] = sha256_text(cj({k: v for k, v in data.items() if k != "data_sha256"}))
        write_json(self.cfg.source_manifest, data)
        stats = build_tables(self.cfg, self.output)
        observations = [n for n in read_jsonl(self.output / "nodes.jsonl") if n["type"] == "Observation"]
        self.assertEqual(len(observations), 3)
        self.assertEqual({n["props"]["value"]["reference"] for n in observations}, {"MD", "TVD"})
        interval = next(n for n in observations if n["props"]["relation"] == "perforated_interval")
        self.assertEqual(interval["props"]["SN_EOR"], "-1")
        self.assertEqual(interval["props"]["value"]["upper"], "5100")
        self.assertEqual(stats["tables"]["mv_eor_perf_intervals"]["orphan"], 1)
