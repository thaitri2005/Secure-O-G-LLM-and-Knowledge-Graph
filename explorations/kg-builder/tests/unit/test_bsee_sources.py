"""Offline source registration integrity and independent dictionary checks."""
from __future__ import annotations

import copy
import csv
import io
import json
import socket
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.build.ingest.bsee_sources import inspect_archive, read_receipt, register_sources
from kgbuilder.core.config import ArchiveSpec, BseeSourceConfig, ConfigError
from kgbuilder.core.text import sha256_file, write_json


def source_fixture(root):
    incoming = root / "incoming"
    (incoming / "dictionaries").mkdir(parents=True)
    cases = json.loads((PROJECT_ROOT / "tests/fixtures/bsee/source_cases.json").read_text())
    page = incoming / "dictionaries/fields.html"
    page.write_text("<p>ID REMARK</p>", encoding="utf-8")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(cases["header"])
    writer.writerows(cases["rows"])
    with zipfile.ZipFile(incoming / "tiny.zip", "w") as archive:
        archive.writestr("tiny.txt", buffer.getvalue())
    receipt = {"format": "kgb.bsee_receipt/1", "snapshot": "synthetic", "files": [],
               "license_status": "synthetic", "attribution": "synthetic"}
    for path, kind in [(incoming / "tiny.zip", "zip"), (page, "dictionary")]:
        receipt["files"].append({"name": path.name, "kind": kind, "required": True,
                                 "status": "ok", "content_check": "pass", "bytes": path.stat().st_size,
                                 "sha256": sha256_file(path), "url": "https://invalid.invalid/inert"})
    write_json(incoming / "receipt.json", receipt)
    cfg = BseeSourceConfig(snapshot="synthetic", receipt=str(incoming / "receipt.json"),
                           archives={"tiny.zip": {"required": True, "members": {"tiny.txt": {
                               "encoding": "utf-8", "header": cases["header"], "allow_columns": cases["header"],
                               "dictionary_ref": "fields.html"}}}}, dictionaries=["fields.html"])
    return incoming, cfg, receipt


class BseeSourcesTest(unittest.TestCase):
    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/bsee_sources")
        self.incoming, self.cfg, self.receipt = source_fixture(self.root)
        self.out = self.root / "registered/manifest.json"

    def register(self, cfg=None):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network")), \
             patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS")), \
             patch.object(urllib.request, "urlopen", side_effect=AssertionError("URL")):
            return register_sources(cfg or self.cfg, self.incoming, self.out)

    def test_multiline_idempotence_bom_and_no_network(self):
        path = self.incoming / "receipt.json"
        path.write_text(path.read_text(), encoding="utf-8-sig")
        self.assertEqual(read_receipt(path)["snapshot"], "synthetic")
        result = self.register()
        before = self.out.read_bytes()
        self.assertEqual(self.register(), result)
        self.assertEqual(self.out.read_bytes(), before)
        self.assertEqual(result["files"]["tiny.zip"]["members"]["tiny.txt"]["verified_by"], "dictionary_tokens")

    def test_receipt_hash_required_optional_and_snapshot(self):
        self.receipt["files"].append({"name": "optional.zip", "required": False, "status": "failed"})
        write_json(self.incoming / "receipt.json", self.receipt)
        self.assertEqual(self.register()["not_acquired"], ["optional.zip"])
        self.out.unlink()
        self.receipt["files"][0]["status"] = "failed"
        write_json(self.incoming / "receipt.json", self.receipt)
        with self.assertRaises(ConfigError): self.register()
        self.assertFalse(self.out.exists())
        self.receipt["files"][0]["status"] = "ok"
        self.receipt["files"][0]["sha256"] = "0" * 64
        write_json(self.incoming / "receipt.json", self.receipt)
        with self.assertRaises(ConfigError): self.register()

    def test_header_dictionary_and_expansion(self):
        for change in ("header", "dictionary", "expansion"):
            cfg = self.cfg.model_dump()
            member = cfg["archives"]["tiny.zip"]["members"]["tiny.txt"]
            if change == "header": member["header"] = ["REMARK", "ID"]
            elif change == "dictionary": member["dictionary_names"] = {"ID": "absent label"}
            else: cfg["max_expanded_bytes"] = 1
            with self.subTest(change=change), self.assertRaises(ConfigError):
                self.register(BseeSourceConfig.model_validate(cfg))
            self.assertFalse(self.out.exists())

    def test_zip_magic_traversal_crc_and_encoding(self):
        path = self.incoming / "bad.zip"
        path.write_bytes(b"<html>")
        with self.assertRaises(ConfigError): inspect_archive(path, ArchiveSpec(required=True))
        cases = json.loads((PROJECT_ROOT / "tests/fixtures/bsee/source_cases.json").read_text())
        for name in cases["unsafe_members"]:
            info = zipfile.ZipInfo("placeholder")
            info.filename = name
            info.orig_filename = name
            with zipfile.ZipFile(path, "w") as archive: archive.writestr(info, "safe")
            with self.assertRaises(ConfigError): inspect_archive(path, ArchiveSpec(required=True))
        with zipfile.ZipFile(path, "w") as archive: archive.writestr("tiny.txt", b"ID,REMARK\n1,\xff\n")
        with self.assertRaises(ConfigError): inspect_archive(path, self.cfg.archives["tiny.zip"])
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive: archive.writestr("tiny.txt", b"ID,REMARK\n1,example\n")
        raw = path.read_bytes().replace(b"example", b"changed")
        path.write_bytes(raw)
        with self.assertRaises(ConfigError): inspect_archive(path, self.cfg.archives["tiny.zip"])

    def test_denylist_and_strict_config(self):
        cfg = self.cfg.model_dump()
        member = cfg["archives"]["tiny.zip"]["members"]["tiny.txt"]
        member["header"].append("CONTACT_NAME")
        member["allow_columns"].append("CONTACT_NAME")
        with self.assertRaises(ValueError): BseeSourceConfig.model_validate(cfg)

    def test_positional_reference_equality(self):
        cfg = self.cfg.model_dump()
        for name, member, contents, header in [
            ("BoreholeRawData.zip", "BoreholeRawData/mv_boreholes_all.txt", "API_WELL_NUMBER,ID\n012345678900,a\n", ["API_WELL_NUMBER", "ID"]),
            ("5010delimit.zip", "5010.txt", "012345678900,a\n", None),
        ]:
            path = self.incoming / name
            with zipfile.ZipFile(path, "w") as archive: archive.writestr(member, contents)
            spec = {"encoding": "utf-8", "allow_columns": ["API_WELL_NUMBER", "ID"], "dictionary_ref": "fields.html"}
            spec["header" if header else "positional"] = ["API_WELL_NUMBER", "ID"]
            cfg["archives"][name] = {"required": True, "members": {member: spec}}
            self.receipt["files"].append({"name": name, "kind": "zip", "required": True, "status": "ok",
                                         "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        page = self.incoming / "dictionaries/fields.html"
        page.write_text("ID REMARK API_WELL_NUMBER", encoding="utf-8")
        self.receipt["files"][1].update(bytes=page.stat().st_size, sha256=sha256_file(page))
        write_json(self.incoming / "receipt.json", self.receipt)
        result = self.register(BseeSourceConfig.model_validate(cfg))
        self.assertEqual(result["positional_equality"]["5010delimit.zip"]["columns"]["ID"]["rate"], 1)
        self.out.unlink()
        path = self.incoming / "5010delimit.zip"
        with zipfile.ZipFile(path, "w") as archive: archive.writestr("5010.txt", "012345678900,b\n")
        self.receipt["files"][-1].update(bytes=path.stat().st_size, sha256=sha256_file(path))
        write_json(self.incoming / "receipt.json", self.receipt)
        with self.assertRaisesRegex(ConfigError, "unverified column.*ID"):
            self.register(BseeSourceConfig.model_validate(cfg))
        self.assertFalse(self.out.exists())
        cfg = self.cfg.model_dump()
        cfg["url"] = "not allowed"
        with self.assertRaises(ValueError): BseeSourceConfig.model_validate(cfg)
