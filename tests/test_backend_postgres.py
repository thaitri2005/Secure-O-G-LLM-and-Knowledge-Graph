"""The question log in PostgreSQL, and the service as the environment configures it (backend/app.py default_service).

The PostgreSQL log runs every test of tests/test_backend.py that the file log runs, against tables of
platform/sql/002_questions.sql in a temporary schema, and the counting query of backend design §3. Tests skip when
the local PostgreSQL or Neo4j does not answer; see tests/test_graphrag_stores.py for how they keep out of the way of
other users of the same databases.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_backend import FRAME_EOW, FRAME_HOURS, ScriptedClient, TestClient, entry, sample_engine  # noqa: E402
from tests import test_backend  # noqa: E402
from tests.test_graphrag_stores import (DSN, NEO4J, NO_NEO4J, NO_POSTGRES, RELEASE, sample_package,  # noqa: E402
                                        temporary_schema)

ROLES = {"frame": {"endpoint": "test", "model": "stand-in"}, "answer": {"endpoint": "test", "model": "stand-in"}}
VARIABLES = ("BACKEND_SOURCE", "BACKEND_DSN", "BACKEND_RELEASE", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")


@unittest.skipIf(TestClient is None or NO_POSTGRES, NO_POSTGRES or "needs backend/requirements.txt (fastapi)")
class PostgresLogBackendTests(test_backend.BackendTests):
    """Every test of the file log's suite, with the log in PostgreSQL. `log()` reads the tables back in the shape of
    the file's lines, so the inherited tests check the same fields."""

    def setUp(self):
        super().setUp()
        from backend.app import create_app
        from backend.questions import PostgresQuestionLog
        from backend.service import Service
        schema = temporary_schema()
        self.dsn = schema.__enter__()
        self.addCleanup(schema.__exit__, None, None, None)
        self.make = lambda frame, answer, fail=False: TestClient(create_app(Service(
            sample_engine(), ScriptedClient(frame, answer, fail), ScriptedClient(frame, answer, fail),
            PostgresQuestionLog(self.dsn), roles=ROLES)))

    def log(self):
        import psycopg
        with psycopg.connect(self.dsn) as conn:
            questions = [(at, 0, {"type": "question", **record})
                         for at, record in conn.execute("SELECT asked_at, record FROM questions").fetchall()]
            feedback = [(at, 1, {"type": "feedback", "question_id": q, "verdict": v, "comment": c, "at": at.isoformat()})
                        for q, v, c, at in conn.execute("SELECT question_id, verdict, comment, at FROM question_feedback "
                                                        "ORDER BY feedback_id").fetchall()]
        return [line for _, _, line in sorted(questions + feedback, key=lambda row: row[:2])]

    def new_log(self):
        from backend.questions import PostgresQuestionLog
        return PostgresQuestionLog(self.dsn)

    def test_times_read_back_in_utc_whatever_the_sessions_time_zone(self):
        from backend.questions import Filters, PostgresQuestionLog
        # The temporary schema's DSN sets `options` already; the session's time zone joins it.
        log = PostgresQuestionLog(self.dsn.replace("options=", "options=-ctimezone%3DAsia%2FHo_Chi_Minh%20", 1))
        with log._connect() as conn:
            self.assertEqual(conn.execute("SHOW timezone").fetchone()[0], "Asia/Ho_Chi_Minh")
        log.add_question(entry("late", asked_at="2026-11-22T23:30:00+00:00"))
        found = log.questions(Filters(date_to="2026-11-22"))[1]
        self.assertEqual([(e["id"], e["asked_at"]) for e in found], [("late", "2026-11-22T23:30:00+00:00")])
        self.assertEqual(log.questions(Filters(date_from="2026-11-23"))[0], 0)

    def test_the_question_log_knows_earlier_questions_without_rereading_the_file(self):
        # The file log's version of this test is about its in-memory index; here a second log sees the first's rows.
        from backend.questions import PostgresQuestionLog
        first = PostgresQuestionLog(self.dsn)
        first.add_question(entry("q1"))
        self.assertTrue(first.has_question("q1"))
        self.assertFalse(first.has_question("q2"))
        self.assertTrue(PostgresQuestionLog(self.dsn).has_question("q1"))

    def test_the_columns_are_taken_from_the_entry(self):
        import psycopg
        body = self.make(FRAME_HOURS, None).post("/v1/questions", json={"question": "How many hours of drilling on AK-3?",
                                                                       "lane": "events"}).json()
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute("SELECT question_id, question, mode, forced_lane, kind, report_type, lanes, fallback, "
                               "answered_from, status, answer_text, calls, record FROM questions").fetchone()
        self.assertEqual(row[:12], (body["id"], "How many hours of drilling on AK-3?", "allow_fallback", "events",
                                    "over_time", "daily", ["events"], False, "daily", "answered", body["answer_text"], 1))
        self.assertEqual(row[12]["cost"], body["cost"])

    def test_the_counting_query_of_the_design_runs(self):
        from backend.questions import COUNTS, PostgresQuestionLog
        import psycopg
        log = PostgresQuestionLog(self.dsn)
        for question_id, kind, status in (("a", "lookup", "answered"), ("b", "lookup", "not_stated"),
                                          ("c", "over_time", "answered"), ("d", "lookup", "answered")):
            log.add_question(entry(question_id, kind, status))
        log.add_feedback("a", "wrong", "should be 1,955 ft")
        log.add_feedback("c", "right", "")
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute(COUNTS).fetchall(), [("lookup", 3, 2, 1), ("over_time", 1, 1, 0)])

    def test_a_question_the_tables_refuse_is_not_logged_by_halves(self):
        import psycopg
        from backend.questions import PostgresQuestionLog
        log = PostgresQuestionLog(self.dsn)
        with self.assertRaises(psycopg.errors.CheckViolation):
            log.add_question(dict(entry("x"), mode="fast"))
        self.assertFalse(log.has_question("x"))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            log.add_feedback("x", "wrong", "")

    def test_the_tables_apply_twice_without_change(self):
        from backend.questions import main
        from contextlib import redirect_stdout
        import io
        self.make(FRAME_EOW, None)  # nothing asked; the schema already holds the tables
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["init", "--dsn", self.dsn]), 0)
            self.assertEqual(main(["init", "--dsn", self.dsn]), 0)
            self.assertEqual(main(["counts", "--dsn", self.dsn]), 0)
        self.assertIn("applied 002_questions.sql", out.getvalue())

    def test_a_log_without_its_tables_fails_at_start(self):
        import psycopg
        from backend.questions import PostgresQuestionLog
        with self.assertRaises(psycopg.errors.UndefinedTable):
            PostgresQuestionLog(f"{DSN}?options=-csearch_path%3Dno_such_schema")


@unittest.skipIf(TestClient is None, "needs backend/requirements.txt (fastapi)")
class DefaultServiceTests(unittest.TestCase):
    """`default_service()` as the environment sets it. Model clients are built but never called here."""

    def service(self, environment: dict, embedding_answers: bool = False):
        import httpx
        from backend import app

        def probe(url, timeout):
            if embedding_answers:
                return httpx.Response(200, request=httpx.Request("GET", url))
            raise httpx.ConnectError("nothing answers")
        with mock.patch.dict(os.environ, environment), mock.patch("httpx.get", probe):
            for name in set(VARIABLES) - set(environment):
                os.environ.pop(name, None)   # restored by patch.dict
            return app.default_service()

    def test_with_nothing_set_it_is_todays_service_on_files(self):
        from backend.questions import JsonlQuestionLog
        from backend.app import QUESTION_LOG, create_app
        for answers, expected in ((False, {"multi_well_retriever": "perwell:bm25"}), (True, {})):
            with mock.patch("graphrag.lanes.Engine.load", return_value=sample_engine()) as load:
                service = self.service({}, embedding_answers=answers)
            load.assert_called_once_with(**expected)
            self.assertIsInstance(service.log, JsonlQuestionLog)
            self.assertEqual(service.log.path, QUESTION_LOG)
            health = TestClient(create_app(service)).get("/v1/health").json()
            self.assertEqual(health["data"]["source"], "files")
            self.assertEqual(health["models"], {"frame": "local-llama:qwen3-8b", "answer": "local-llama:qwen3-8b"})

    def test_a_wrong_source_or_stores_without_a_database_is_refused(self):
        with self.assertRaisesRegex(ValueError, "BACKEND_SOURCE"):
            self.service({"BACKEND_SOURCE": "neo4j"})
        with self.assertRaisesRegex(ValueError, "needs BACKEND_DSN"):
            self.service({"BACKEND_SOURCE": "stores"})

    def test_an_unreachable_question_log_fails_instead_of_falling_back_to_the_file(self):
        try:
            import psycopg
        except ImportError:
            self.skipTest("needs psycopg")
        with mock.patch("graphrag.lanes.Engine.load", return_value=sample_engine()), \
                self.assertRaises(psycopg.OperationalError):
            self.service({"BACKEND_DSN": "postgresql://kg:x@127.0.0.1:1/kg?connect_timeout=2"})

    @unittest.skipIf(NO_POSTGRES or NO_NEO4J, NO_POSTGRES or NO_NEO4J or "")
    def test_with_the_stores_health_says_stores_and_questions_go_to_postgresql(self):
        from backend.app import create_app
        from backend.questions import PostgresQuestionLog
        with temporary_schema(sample_package()) as dsn:
            service = self.service({"BACKEND_SOURCE": "stores", "BACKEND_DSN": dsn, "NEO4J_URI": NEO4J[0],
                                    "NEO4J_USER": NEO4J[1], "NEO4J_PASSWORD": NEO4J[2]})
            self.assertIsInstance(service.log, PostgresQuestionLog)
            health = TestClient(create_app(service)).get("/v1/health").json()["data"]
            self.assertEqual((health["source"], health["end_of_well_chunks"], health["daily_chunks"]), ("stores", 2, 2))
            # A release named that the store does not hold fails loudly too.
            with self.assertRaisesRegex(LookupError, "not in the store"):
                self.service({"BACKEND_SOURCE": "stores", "BACKEND_DSN": dsn, "BACKEND_RELEASE": f"{RELEASE}-2"})

    @unittest.skipIf(NO_POSTGRES, NO_POSTGRES or "")
    def test_with_the_stores_an_unreachable_neo4j_fails_at_start(self):
        from neo4j.exceptions import ServiceUnavailable
        with temporary_schema(sample_package()) as dsn, self.assertRaises(ServiceUnavailable):
            self.service({"BACKEND_SOURCE": "stores", "BACKEND_DSN": dsn, "NEO4J_URI": "bolt://127.0.0.1:1"})


if __name__ == "__main__":
    unittest.main()
