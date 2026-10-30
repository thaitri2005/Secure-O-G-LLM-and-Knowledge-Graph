"""Gold commands operate only on the synthetic test root."""
from __future__ import annotations

import unittest
import json
import shutil

from helpers import run_kgb
from unit.test_well_gold import FIXTURE, TEST_CONFIG, amendment_fixture, gold_fixture, post_amendment_fixture


class WellGoldCliTest(unittest.TestCase):
    def test_v2_prepare_and_verify(self):
        from unit.test_well_gold import TEST_CONFIG_V2
        cfg = gold_fixture(config=TEST_CONFIG_V2)
        self.assertEqual(json.loads((cfg["root"] / "freeze.json").read_text())["converter"], "v2")
        for role in ("annotator_a", "annotator_b"):
            result = run_kgb(["domain", "gold", "validate", "--config", str(TEST_CONFIG_V2), "--annotator", role])
            self.assertEqual(result.returncode, 0, result.stderr)
        gold_fixture(complete=True, config=TEST_CONFIG_V2)
        result = run_kgb(["domain", "gold", "verify", "--config", str(TEST_CONFIG_V2)])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_post_adjudication_cli_recertification(self):
        cfg, config, probe = post_amendment_fixture(chain=True); root = cfg["root"]
        args = ["--config", str(config)]
        probe.write_text("post CLI change\n", encoding="utf-8")
        command = ["domain", "gold", "amend", *args, "--reason", "Synthetic post-adjudication CLI amendment"]
        result = run_kgb(command); self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual((output["amendment"], output["state"], output["regenerated"]["packets"]), (2, "post_adjudication", "identical"))
        result = run_kgb(command); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "no change")
        for role in ("annotator_a", "annotator_b"):
            result = run_kgb(["domain", "gold", "seal", *args, "--annotator", role])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(json.loads(result.stdout)["amendment_changes"]), 2 if role == "annotator_a" else 1)
        result = run_kgb(["domain", "gold", "adjudication-packet", *args])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["recertified"])
        result = run_kgb(["domain", "gold", "seal", *args, "--annotator", "adjudicator"])
        self.assertEqual(result.returncode, 0, result.stderr)
        for mode in ("merge", "verify"):
            result = run_kgb(["domain", "gold", mode, *args])
            self.assertEqual(result.returncode, 0, result.stderr)
        status, changes = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(status["amendments"], "OK")
        self.assertEqual([row["amendment"] for row in changes["amendment_changes"]["annotator_a"]], [1, 2])

    def test_amendment_cli_sequence(self):
        cfg, config, probe = amendment_fixture(); root = cfg["root"]
        args = ["--config", str(config)]
        missing = run_kgb(["domain", "gold", "amend", *args])
        self.assertEqual(missing.returncode, 2)
        probe.write_text("after\n", encoding="utf-8")
        command = ["domain", "gold", "amend", *args, "--reason", "Synthetic CLI amendment"]
        first = run_kgb(command); self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        self.assertEqual(result["amendment"], 1)
        second = run_kgb(command); self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["status"], "no change")
        for role in ("annotator_a", "annotator_b"):
            sealed = run_kgb(["domain", "gold", "seal", *args, "--annotator", role])
            self.assertEqual(sealed.returncode, 0, sealed.stderr)
        packet = run_kgb(["domain", "gold", "adjudication-packet", *args])
        self.assertEqual(packet.returncode, 0, packet.stderr)
        shutil.copytree(FIXTURE / "adjudication", root / "adjudication", dirs_exist_ok=True)
        sealed = run_kgb(["domain", "gold", "seal", *args, "--annotator", "adjudicator"])
        self.assertEqual(sealed.returncode, 0, sealed.stderr)
        merged = run_kgb(["domain", "gold", "merge", *args]); self.assertEqual(merged.returncode, 0, merged.stderr)
        verified = run_kgb(["domain", "gold", "verify", *args]); self.assertEqual(verified.returncode, 0, verified.stderr)
        status, changes = [json.loads(line) for line in verified.stdout.splitlines()]
        self.assertEqual(status["amendments"], "OK")
        self.assertEqual(changes["amendment_changes"]["annotator_a"][0], {"amendment": 1, "flagged": len(result["flagged"]["annotator_a"]),
                         "changed": 0, "changed_by_path": {}, "changed_by_relation": {}, "flagged_unchanged": len(result["flagged"]["annotator_a"])})

    def test_locations_only_cli(self):
        cfg, config, probe = amendment_fixture(dates=True)
        probe.write_text("after\n", encoding="utf-8")
        args = ["--config", str(config)]
        amended = run_kgb(["domain", "gold", "amend", *args, "--reason", "Synthetic dates"])
        self.assertEqual(amended.returncode, 0, amended.stderr)
        flagged = json.loads(amended.stdout)["flagged"]["annotator_a"]
        result = run_kgb(["domain", "gold", "validate", *args, "--annotator", "annotator_a", "--locations-only"])
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("3-14-2011", result.stdout + result.stderr)
        self.assertNotIn("2011-03-14", result.stdout + result.stderr)
        for location in flagged: self.assertIn(location, result.stderr)
        self.assertNotIn("date normalization mismatch", result.stderr)

    def test_validate_seal(self):
        gold_fixture()
        args = ["--config", str(TEST_CONFIG), "--annotator", "annotator_b"]
        for mode in ("validate", "seal"):
            result = run_kgb(["domain", "gold", mode, *args])
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(run_kgb(["domain", "gold", "seal", *args]).returncode, 2)

    def test_complete_sequence(self):
        import shutil
        from unit.test_well_gold import FIXTURE
        cfg = gold_fixture()
        for role in ("annotator_a", "annotator_b"):
            result = run_kgb(["domain", "gold", "seal", "--config", str(TEST_CONFIG), "--annotator", role])
            self.assertEqual(result.returncode, 0, result.stderr)
        result = run_kgb(["domain", "gold", "adjudication-packet", "--config", str(TEST_CONFIG)])
        self.assertEqual(result.returncode, 0, result.stderr)
        shutil.copytree(FIXTURE / "adjudication", cfg["root"] / "adjudication", dirs_exist_ok=True)
        result = run_kgb(["domain", "gold", "seal", "--config", str(TEST_CONFIG), "--annotator", "adjudicator"])
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("merge", "verify"):
            result = run_kgb(["domain", "gold", command, "--config", str(TEST_CONFIG)])
            self.assertEqual(result.returncode, 0, result.stderr)
