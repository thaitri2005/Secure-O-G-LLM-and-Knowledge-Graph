"""The release runner (backend design §6): step order and failures with stand-ins, the embedding step with a stand-in
embedding model against PostgreSQL, the run record, and the graphs rebuilt from a K1 release. Tests that need a
store skip when it cannot be reached; tests that need the release skip when it is not on this machine. The release
is found in data/interim/k1/ or at PLATFORM_K1_RELEASE, appendix 23's corpus export at PLATFORM_APPENDICES."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform"))

import run_release  # noqa: E402


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


def release_folder() -> Path | None:
    if os.environ.get("PLATFORM_K1_RELEASE"):
        return Path(os.environ["PLATFORM_K1_RELEASE"])
    found = sorted((ROOT / "data/interim/k1").glob("*/manifest.json"))
    return found[0].parent if len(found) == 1 else None


def appendices_folder() -> Path:
    return Path(os.environ.get("PLATFORM_APPENDICES") or run_release.event_graph.OLD_EXPORT)


def postgres():
    import psycopg
    try:
        return psycopg.connect(run_release.DSN, connect_timeout=3)
    except psycopg.OperationalError as error:
        raise unittest.SkipTest(f"PostgreSQL not reachable: {error}")


class StepTests(unittest.TestCase):
    def run_of(self, folder: str) -> run_release.Run:
        return run_release.Run(Path(folder), "test-release", Path(folder))

    def test_steps_run_in_order_and_the_first_failure_stops_the_run(self):
        called = []

        def ok(name):
            return lambda run: called.append(name) or {"n": 1}

        def fails(run):
            called.append("load chunks")
            raise run_release.StepFailed("3 problems")

        steps = [("validate", ok("validate")), ("load chunks", fails), ("build events", ok("build events"))]
        with tempfile.TemporaryDirectory() as folder, quiet():
            counts, seconds, failed, reason = run_release.run_steps(self.run_of(folder), steps)
        self.assertEqual(called, ["validate", "load chunks"])
        self.assertEqual((counts, failed, reason), ({"validate": {"n": 1}}, "load chunks", "3 problems"))
        self.assertEqual(set(seconds), {"validate", "load chunks"})

    def test_an_exit_or_an_error_inside_a_step_is_a_failure_with_its_name(self):
        def exits(run):
            raise SystemExit("name a release with --release")

        with tempfile.TemporaryDirectory() as folder, quiet():
            *_, failed, reason = run_release.run_steps(self.run_of(folder), [("embed", exits)])
        self.assertEqual((failed, reason), ("embed", "SystemExit: name a release with --release"))
        self.assertEqual(run_release.number("embed"), 3)
        self.assertEqual(run_release.number("load facts"), 7)

    def test_the_embedding_step_stops_on_either_check(self):
        with tempfile.TemporaryDirectory() as folder:
            run = self.run_of(folder)
            with mock.patch.object(run_release.embed_k1, "embed", return_value=1) as embed:
                with self.assertRaisesRegex(run_release.StepFailed, "not one per chunk"):
                    run_release.step_embed(run)
            self.assertEqual((embed.call_args.args[0].release, embed.call_args.args[0].model),
                             ("test-release", run_release.embed_k1.MODEL))
            with mock.patch.object(run_release.embed_k1, "embed", return_value=0), \
                    mock.patch.object(run_release.embed_k1, "check", return_value=1):
                with self.assertRaisesRegex(run_release.StepFailed, "different top 5"):
                    run_release.step_embed(run)

    def test_an_unchanged_release_is_kept_and_checked_and_reload_replaces_it(self):
        package = {"sums_sha256": "abc", "legacy": [], **{name: [{}] for name in run_release.GROUPS}}
        for stored, reload, loads in [(("abc",), False, False), (("abc",), True, True), (("old",), False, True),
                                      (None, False, True)]:
            cursor = mock.MagicMock()
            cursor.fetchone.return_value = stored
            connection = mock.MagicMock()
            connection.__enter__.return_value.cursor.return_value.__enter__.return_value = cursor
            with tempfile.TemporaryDirectory() as folder, quiet(), \
                    mock.patch.object(run_release.psycopg, "connect", return_value=connection), \
                    mock.patch.object(run_release.load_k1, "read_package", return_value=package), \
                    mock.patch.object(run_release.load_k1, "load") as load, \
                    mock.patch.object(run_release.load_k1, "check", return_value=[]) as check:
                run = self.run_of(folder)
                run.reload = reload
                counts = run_release.step_load_chunks(run)
            self.assertEqual(load.called, loads, (stored, reload))
            check.assert_called_once()
            self.assertEqual(counts["chunks"], 1)
            self.assertIn("kept" if not loads else "loaded", run.notes["load chunks"])

    def test_a_release_that_does_not_read_back_stops_step_2(self):
        package = {"sums_sha256": "abc", "legacy": [], **{name: [] for name in run_release.GROUPS}}
        connection = mock.MagicMock()
        connection.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = None
        with tempfile.TemporaryDirectory() as folder, quiet(), \
                mock.patch.object(run_release.psycopg, "connect", return_value=connection), \
                mock.patch.object(run_release.load_k1, "read_package", return_value=package), \
                mock.patch.object(run_release.load_k1, "load"), \
                mock.patch.object(run_release.load_k1, "check", return_value=["chunks: 3 rows, manifest says 4"]):
            with self.assertRaisesRegex(run_release.StepFailed, "1 problems reading the release back"):
                run_release.step_load_chunks(self.run_of(folder))

    def test_main_skips_steps_and_records_a_failed_run(self):
        records, ran = [], []
        steps = [(name, (lambda name: lambda run: ran.append(name) or {"n": 1})(name)) for name, _ in run_release.STEPS]
        steps[1] = ("load chunks", mock.Mock(side_effect=run_release.StepFailed("rows differ")))
        with tempfile.TemporaryDirectory() as folder, quiet():
            release = Path(folder) / "rel-1"
            release.mkdir()
            (release / "SHA256SUMS").write_bytes(b"abc  manifest.json\n")
            with mock.patch.object(run_release, "STEPS", steps), \
                    mock.patch.object(run_release, "record_run", side_effect=lambda dsn, r: records.append(r)):
                code = run_release.main([str(release), "--skip-vectors", "--out", folder])
                self.assertEqual(code, 1)
                self.assertEqual(ran, ["validate"])
                code = run_release.main([str(release), "--skip-vectors", "--skip-graphs", "--out", folder])
        failed, _ = records
        self.assertEqual((failed["status"], failed["failed_step"], failed["error"]), ("failed", "load chunks", "rows differ"))
        self.assertEqual(failed["release"], "rel-1")
        self.assertEqual(failed["sha256sums_sha256"], hashlib.sha256(b"abc  manifest.json\n").hexdigest())
        self.assertIsNone(failed["embedding_model"])
        self.assertEqual(records[1]["skipped"], ["embed", "build events", "build facts", "load events", "load facts"])
        self.assertEqual(failed["facts"], "recorded")   # no legacy map in the release

    def test_facts_are_moved_onto_the_release_ids_by_default_when_it_holds_a_legacy_map(self):
        fact = {"well": "68-32", "property": "casing_depth", "value": "978", "qualifier": "actual",
                "context": {"casing_size_in": "9-5/8"}, "chunk": "old#c1", "source": "table_mapping"}
        with tempfile.TemporaryDirectory() as folder, quiet():
            release, recorded = Path(folder) / "rel-1", Path(folder) / "recorded.graph.json"
            release.mkdir()
            self.assertEqual(run_release.default_facts(release), "recorded")
            recorded.write_text(json.dumps(run_release.to_graph([fact, dict(fact, value="40", chunk="old#c2")])),
                                encoding="utf-8")
            (release / "legacy_chunk_ids.json").write_text(json.dumps([{"old_chunk_id": "old#c1", "new_chunk_id": "fa:s1:c0"}]),
                                                           encoding="utf-8")
            (release / "chunks.jsonl").write_text(json.dumps({"chunk_id": "fa:s1:c0", "doc_id": "d", "page": 1, "type": "text",
                                                              "text": "Well 68-32: 9-5/8 casing set at 978 ft."}) + "\n",
                                                  encoding="utf-8")
            self.assertEqual(run_release.default_facts(release), "mapped")
            run = run_release.Run(release, "rel-1", Path(folder), facts="mapped")
            with mock.patch.object(run_release.load_facts_neo4j, "GRAPH", recorded):
                counts = run_release.step_build_facts(run)
            written = json.loads(run.written["facts"].read_text(encoding="utf-8"))
        self.assertEqual((counts["facts"], counts["facts_on_new_ids"], counts["facts_on_old_ids"]), (2, 1, {"no mapping": 1}))
        self.assertEqual(sorted(n["key"] for n in written["nodes"] if n["label"] == "Chunk"), ["fa:s1:c0", "old#c2"])
        self.assertEqual(written["facts_on_new_ids"], 1)
        self.assertIn("1 of 2 facts on its IDs", run.notes["build facts"])


class FakeEmbeddings:
    """Stands in for the embedding server: a fixed random unit vector per text, the same text giving the same one."""

    def __init__(self):
        self.calls = self.tokens = 0
        self.ledger = SimpleNamespace(summary=lambda: {"calls": self.calls, "prompt_tokens": self.tokens})

    def embed(self, texts):
        self.calls += 1
        self.tokens += sum(len(t.split()) for t in texts)
        return [np.random.default_rng(int.from_bytes(hashlib.sha256(t.encode()).digest()[:8], "little"))
                .standard_normal(1024) for t in texts]


class PostgresTests(unittest.TestCase):
    def test_the_embedding_step_with_a_stand_in_model(self):
        with postgres() as conn, conn.cursor() as cur:
            cur.execute("SELECT release FROM k1_releases ORDER BY release LIMIT 1")
            row = cur.fetchone()
        if row is None:
            self.skipTest("no K1 release loaded in PostgreSQL")
        model = f"test-fake-embedding-{uuid.uuid4().hex[:8]}"
        self.addCleanup(self.remove_vectors, model)
        with tempfile.TemporaryDirectory() as folder, quiet():
            run = run_release.Run(Path(folder), row[0], Path(folder), embedding_model=model)
            with mock.patch.object(run_release.embed_k1, "client", return_value=FakeEmbeddings()):
                counts = run_release.step_embed(run)
        with postgres() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM chunks c JOIN files f USING (file_id) WHERE f.release = %s", (row[0],))
            self.assertEqual(counts, {"vectors": cur.fetchone()[0]})

    def remove_vectors(self, model: str):
        with postgres() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM chunk_vectors WHERE embedding_model = %s", (model,))

    def test_the_run_record_and_the_comparison_with_the_previous_run(self):
        release = f"test-release-{uuid.uuid4().hex[:8]}"
        self.addCleanup(self.remove_runs, release)
        record = {"release": release, "sha256sums_sha256": "0" * 64, "status": "succeeded", "skipped": ["embed"],
                  "facts": "recorded",
                  "started_at": "2026-11-24T10:00:00+00:00", "finished_at": "2026-11-24T10:01:00+00:00",
                  "counts": {"load events": {"npt": (115.0, 28, 10), "events": 161}}}
        self.assertIsNone(run_release.record_run(run_release.DSN, {**record, "run_id": f"{release}-1"}))
        later = {**record, "started_at": "2026-11-24T11:00:00+00:00"}
        again = run_release.record_run(run_release.DSN, {**later, "run_id": f"{release}-2"})
        self.assertEqual(again, {"run_id": f"{release}-1", "same_counts": True})
        changed = {**later, "run_id": f"{release}-3", "counts": {"load events": {"events": 160}}}
        self.assertEqual(run_release.record_run(run_release.DSN, changed), {"run_id": f"{release}-2", "same_counts": False})
        other_options = {**later, "run_id": f"{release}-4", "facts": "tables"}   # compared only with like runs
        self.assertIsNone(run_release.record_run(run_release.DSN, other_options))
        with postgres() as conn, conn.cursor() as cur:
            cur.execute("SELECT run_id, status, record ->> 'sha256sums_sha256' FROM runs WHERE release = %s "
                        "ORDER BY run_id", (release,))
            self.assertEqual([r[0] for r in cur.fetchall()], [f"{release}-{n}" for n in (1, 2, 3, 4)])

    def remove_runs(self, release: str):
        with postgres() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM runs WHERE release = %s", (release,))


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.release = release_folder()
        if self.release is None or not (self.release / "chunks.jsonl").is_file():
            self.skipTest("no K1 release on this machine (data/interim/k1/ or PLATFORM_K1_RELEASE)")

    def test_the_event_graph_from_the_release_equals_e31(self):
        has_npt = any(run_release.NPT in json.loads(line)["doc_id"]
                      for line in (self.release / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if line)
        if not has_npt and not (appendices_folder() / "chunks.jsonl").is_file():
            self.skipTest("appendix 23 is neither in the release nor in a corpus export (PLATFORM_APPENDICES)")
        with tempfile.TemporaryDirectory() as folder:
            run = run_release.Run(self.release, self.release.name, Path(folder), appendices=appendices_folder())
            counts = run_release.step_build_events(run)
            built = json.loads(run.written["events"].read_text(encoding="utf-8"))
        recorded = json.loads((ROOT / "graphrag/results/E31_events_k1.json").read_text(encoding="utf-8"))
        self.assertEqual((counts["events"], counts["days"]), (161, 27))
        # E31 was built from the candidate release and an older export of appendix 23, so its chunk IDs differ, and
        # the demo package's Operations Summary rule recovers words in some descriptions (Track A log A-F15). What an
        # event measures must be the same.
        measured = ("date", "start", "end", "hours", "end_md", "code", "npt_code")
        self.assertEqual([[e[k] for k in measured] for e in built["events"]],
                         [[e[k] for k in measured] for e in recorded["events"]])
        self.assertEqual(built["wells"], ["AK-3"])

    def test_the_fact_graph_from_the_release_tables_needs_no_model(self):
        graph, counts = run_release.release_fact_graph(self.release)
        self.assertEqual(counts["facts_kept"], sum(n["label"] == "Fact" for n in graph["nodes"]))
        self.assertGreater(counts["facts_kept"], 0)
        self.assertEqual(run_release.load_facts_neo4j.check_file(graph), [])
        chunks = [n["key"] for n in graph["nodes"] if n["label"] == "Chunk"]
        self.assertTrue(chunks and all("#" not in c for c in chunks))   # K1 version 1 IDs

    def test_the_recorded_facts_move_onto_the_release_ids_and_keep_their_number(self):
        if not (self.release / "legacy_chunk_ids.json").is_file():
            self.skipTest("the release holds no legacy map")
        graph, counts = run_release.map_to_release(self.release)
        recorded = json.loads(run_release.load_facts_neo4j.GRAPH.read_text(encoding="utf-8"))
        self.assertEqual(counts["facts"], recorded["facts_kept"])
        self.assertEqual(sum(n["label"] == "Fact" for n in graph["nodes"]), recorded["facts_kept"])
        self.assertEqual(run_release.load_facts_neo4j.check_file(graph), [])
        held = {json.loads(line)["chunk_id"] for line in (self.release / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if line}
        new = {n["key"] for n in graph["nodes"] if n["label"] == "Chunk" and "#" not in n["key"]}
        self.assertTrue(new and new <= held)


class SqlTests(unittest.TestCase):
    def test_the_runs_table_matches_the_fixed_interface_and_can_be_applied_twice(self):
        sql = run_release.RUNS_SQL.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS runs", sql)
        for column in ("run_id", "release", "started_at", "finished_at", "status", "record"):
            self.assertIn(f"\n    {column} ", sql)
        self.assertNotIn("\r", sql)
        with postgres() as conn, conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(sql)
            cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'runs' "
                        "ORDER BY ordinal_position")
            self.assertEqual(cur.fetchall(), [("run_id", "text"), ("release", "text"),
                                              ("started_at", "timestamp with time zone"),
                                              ("finished_at", "timestamp with time zone"), ("status", "text"),
                                              ("record", "jsonb")])
            conn.rollback()


if __name__ == "__main__":
    unittest.main()
