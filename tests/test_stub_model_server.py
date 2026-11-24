"""The stub model server (scripts/stub_model_server.py): schema-valid, deterministic, labelled replies, and a question
through the real model client and the backend that completes against it. No GPU, network or store needed."""
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path

import httpx

from graphrag import baseline, coordinator, events
from graphrag.client import Endpoint, ModelClient

try:
    from fastapi.testclient import TestClient
except ImportError:  # the backend's packages are in backend/requirements.txt, not in the main lock file
    TestClient = None

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stub_model_server", ROOT / "scripts" / "stub_model_server.py")
stub = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stub)

PROMPT = [{"role": "system", "content": "You answer questions."},
          {"role": "user", "content": "Passages:\n\n[c0002] (page 3) AK-3 reached a total depth of 1,955 feet on "
                                      "20 August.\n\n[c0013] (page 7) Casing was set.\n\nQuestion: How deep?"}]


def valid(value, schema) -> bool:
    """A small validator for the subset of JSON Schema the engine sends (no jsonschema package in the lock)."""
    if "enum" in schema:
        return value in schema["enum"]
    kind = schema.get("type")
    if kind == "object":
        props = schema.get("properties", {})
        return (isinstance(value, dict) and set(schema.get("required", [])) <= set(value)
                and (schema.get("additionalProperties", True) or set(value) <= set(props))
                and all(valid(value[k], props[k]) for k in value if k in props))
    if kind == "array":
        return (isinstance(value, list) and len(value) >= schema.get("minItems", 0)
                and len(value) <= schema.get("maxItems", len(value)) and all(valid(v, schema["items"]) for v in value))
    if kind == "string":
        return isinstance(value, str) and len(value) <= schema.get("maxLength", len(value))
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    return True


class StubReplies(unittest.TestCase):
    def test_every_schema_the_engine_sends_gets_valid_json(self):
        schemas = {"frame": coordinator.FRAME_SCHEMA, "plan": events.PLAN_SCHEMA, **baseline.ANSWER_FORMATS}
        for name, schema in schemas.items():
            body = {"model": "qwen3-8b", "messages": PROMPT,
                    "response_format": {"type": "json_schema", "json_schema": {"name": "output", "strict": True, "schema": schema}}}
            parsed = json.loads(stub.chat_response(body)["choices"][0]["message"]["content"])
            self.assertTrue(valid(parsed, schema), (name, parsed))

    def test_an_answer_cites_the_first_passage_with_a_verbatim_quote_and_is_labelled(self):
        body = {"model": "qwen3-8b", "messages": PROMPT, "response_format": {
            "type": "json_schema", "json_schema": {"schema": baseline.ANSWER_FORMATS["evidence_first"]}}}
        parsed = json.loads(stub.chat_response(body)["choices"][0]["message"]["content"])
        answer = parsed["answers"][0]
        self.assertEqual(answer["chunk"], "c0002")
        self.assertIn(answer["quote"], PROMPT[1]["content"])
        self.assertTrue(answer["value"].startswith("[stub model]"))
        self.assertTrue(parsed["evidence"].startswith("[stub model]"))
        self.assertEqual(answer["unit"], "")

    def test_a_frame_is_one_the_coordinator_accepts(self):
        body = {"messages": [{"role": "user", "content": "What depth did AK-3 reach?"}],
                "response_format": {"type": "json_schema", "json_schema": {"schema": coordinator.FRAME_SCHEMA}}}
        parsed = json.loads(stub.chat_response(body)["choices"][0]["message"]["content"])
        self.assertEqual((parsed["kind"], parsed["report_type"], parsed["well"]), ("lookup", "end_of_well", ""))

    def test_replies_are_deterministic_and_plain_text_is_labelled(self):
        body = {"model": "qwen3-8b", "messages": PROMPT}
        self.assertEqual(stub.chat_response(body), stub.chat_response(json.loads(json.dumps(body))))
        self.assertTrue(stub.chat_response(body)["choices"][0]["message"]["content"].startswith("[stub model]"))
        self.assertGreater(stub.chat_response(body)["usage"]["prompt_tokens"], 0)

    def test_embeddings_are_deterministic_unit_vectors(self):
        out = stub.embedding_response({"model": "qwen3-embedding-0.6b", "input": ["a", "b", "a"]})
        vectors = [row["embedding"] for row in out["data"]]
        self.assertEqual(([row["index"] for row in out["data"]], vectors[0]), ([0, 1, 2], vectors[2]))
        self.assertNotEqual(vectors[0], vectors[1])
        self.assertAlmostEqual(sum(x * x for x in vectors[0]), 1.0, places=4)
        self.assertEqual(len(stub.embedding_response({"input": "one"})["data"]), 1)

    def test_lengths_and_numbers_respect_the_schema(self):
        self.assertEqual(stub.instance({"type": "string", "maxLength": 5}, []), "[stub")
        self.assertEqual(stub.instance({"type": "integer", "minimum": 2}, []), 2)
        self.assertEqual(stub.instance({"type": "array", "maxItems": 0, "items": {"type": "string"}}, []), [])
        self.assertEqual(stub.instance({"anyOf": [{"type": "boolean"}, {"type": "string"}]}, []), False)


class StubServer(unittest.TestCase):
    """The server on a free port, called by the project's own model client."""

    @classmethod
    def setUpClass(cls):
        cls.server = stub.make_server("127.0.0.1", 0, quiet=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def client(self, model="qwen3-8b"):
        return ModelClient(Endpoint("stub", self.base, False), model, cache_dir=None, timeout=10)

    def test_routes(self):
        self.assertEqual([m["id"] for m in httpx.get(f"{self.base}/models").json()["data"]], list(stub.MODELS))
        self.assertEqual(httpx.get(f"{self.base}/nothing").status_code, 404)
        self.assertEqual(httpx.post(f"{self.base}/chat/completions", content=b"not json").status_code, 400)

    def test_the_model_client_gets_parsed_json_and_embeddings(self):
        call = self.client().chat(PROMPT, schema=baseline.ANSWER_SCHEMA)
        self.assertEqual(call.parsed["status"], "answered")
        self.assertEqual(len(self.client("qwen3-embedding-0.6b").embed(["x", "y"])), 2)

    def test_a_coordinator_answer_completes(self):
        from tests.test_backend import sample_engine
        row = coordinator.answer({"id": "q1", "kind": "live", "question": "What total depth did well AK-3 reach?", "gold": []},
                                 sample_engine(), self.client(), self.client())
        self.assertEqual((row["status"], row["calls"], row["lanes"]), ("answered", 2, ["well_facts", "passages"]))
        self.assertTrue(row["values"][0].startswith("[stub model]"))

    @unittest.skipIf(TestClient is None, "needs backend/requirements.txt (fastapi)")
    def test_a_question_through_the_backend_completes_and_says_it_is_a_stub(self):
        from backend.app import create_app
        from backend.questions import JsonlQuestionLog
        from backend.service import Service
        from tests.test_backend import sample_engine
        with tempfile.TemporaryDirectory() as folder:
            roles = {"frame": {"endpoint": "stub", "model": "qwen3-8b"}, "answer": {"endpoint": "stub", "model": "qwen3-8b"}}
            app = create_app(Service(sample_engine(), self.client(), self.client(),
                                     JsonlQuestionLog(Path(folder, "questions.jsonl")), roles))
            body = TestClient(app).post("/v1/questions", json={"question": "What total depth did well AK-3 reach?"}).json()
        self.assertEqual(body["status"], "answered")
        self.assertTrue(body["answer_text"].startswith("[stub model]"))
        self.assertEqual(body["citations"][0]["file_id"], "gdr882_ak3_eowr")


if __name__ == "__main__":
    unittest.main()
