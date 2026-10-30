"""Track B baseline pieces without any model call: client guard, cache and ledger; BM25; fusion; scoring."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from graphrag.client import Endpoint, ModelClient, PrivateDataError
from graphrag.data import Chunk
from graphrag.retrieval import BM25, Fusion
from graphrag.citations import resolve
from graphrag.scoring import normalize, score_answer, same_value

HOSTED = Endpoint("openrouter", "https://example.invalid/v1", True, None, 1.0, 2.0)
LOCAL = Endpoint("local-llama", "http://127.0.0.1:9/v1", False)


def reply(content, prompt=100, completion=20, cost=None):
    usage = {"prompt_tokens": prompt, "completion_tokens": completion}
    if cost is not None:
        usage["cost"] = cost
    request = httpx.Request("POST", "https://example.invalid")
    return httpx.Response(200, request=request, json={"model": "m", "usage": usage,
                                                      "choices": [{"message": {"content": content}}]})


class ClientTests(unittest.TestCase):
    def test_private_data_never_reaches_a_hosted_endpoint(self):
        client = ModelClient(HOSTED, "m", cache_dir=None)
        with patch("graphrag.client.httpx.post") as post:
            with self.assertRaises(PrivateDataError):
                client.chat([{"role": "user", "content": "x"}], data_class="private")
            post.assert_not_called()

    def test_local_endpoint_accepts_private_data(self):
        client = ModelClient(LOCAL, "m", cache_dir=None)
        with patch("graphrag.client.httpx.post", return_value=reply("hi")):
            self.assertEqual(client.chat([{"role": "user", "content": "x"}], data_class="private").content, "hi")

    def test_cost_from_prices_and_cache_hit_is_free(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = ModelClient(HOSTED, "m", cache_dir=Path(temporary))
            messages = [{"role": "user", "content": "x"}]
            with patch("graphrag.client.httpx.post", return_value=reply('{"a": 1}', 1_000_000, 500_000)) as post:
                first = client.chat(messages, schema={"type": "object"})
                second = client.chat(messages, schema={"type": "object"})
            self.assertEqual(post.call_count, 1)
            self.assertEqual(first.cost_usd, 2.0)
            self.assertEqual((second.cached, second.cost_usd, second.parsed), (True, 0.0, {"a": 1}))
            summary = client.ledger.summary()
            self.assertEqual((summary["calls"], summary["cached_calls"], summary["cost_usd"]), (2, 1, 2.0))

    def test_reported_cost_wins_and_invalid_json_is_counted(self):
        client = ModelClient(HOSTED, "m", cache_dir=None)
        with patch("graphrag.client.httpx.post", return_value=reply("not json", cost=0.003)):
            call = client.chat([{"role": "user", "content": "x"}], schema={"type": "object"})
        self.assertIsNone(call.parsed)
        self.assertEqual((call.cost_usd, client.ledger.invalid_json), (0.003, 1))

    def test_embeddings_keep_input_order_and_are_counted(self):
        client = ModelClient(LOCAL, "e", cache_dir=None)
        request = httpx.Request("POST", "http://127.0.0.1:9")
        response = httpx.Response(200, request=request, json={
            "usage": {"prompt_tokens": 7},
            "data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]})
        with patch("graphrag.client.httpx.post", return_value=response):
            self.assertEqual(client.embed(["a", "b"]), [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual((client.ledger.calls, client.ledger.prompt_tokens), (1, 7))

    def test_schema_is_sent_as_response_format(self):
        client = ModelClient(LOCAL, "m", cache_dir=None)
        with patch("graphrag.client.httpx.post", return_value=reply("{}")) as post:
            client.chat([{"role": "user", "content": "x"}], schema={"type": "object"})
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["response_format"]["json_schema"]["schema"], {"type": "object"})
        self.assertNotIn("usage", body)


def chunk(n, text, section=None):
    return Chunk(f"d#c{n:04d}", "d", 1, "text", section, text)


class RetrievalTests(unittest.TestCase):
    chunks = [chunk(0, "The well was drilled to a total depth of 1,955 feet."),
              chunk(1, "Mud weight and rheology were stable."),
              chunk(2, "Rig released on 6 September.", section="Drilling Summary")]

    def test_bm25_ranks_the_matching_chunk_first(self):
        self.assertEqual(BM25(self.chunks).search("What total depth was drilled?", 1)[0][0], "d#c0000")

    def test_section_heading_is_searchable(self):
        self.assertEqual(BM25(self.chunks).search("drilling summary", 1)[0][0], "d#c0002")

    def test_fusion_combines_rankings(self):
        bm25 = BM25(self.chunks)
        fused = Fusion([bm25, bm25]).search("mud weight", 2)
        self.assertEqual(fused[0][0], "d#c0001")


class ScoringTests(unittest.TestCase):
    depth = {"id": "g01", "value": 1955}
    casing = {"id": "g17", "value": 221.7, "alternatives": [220]}

    def test_values_match_like_the_prototype(self):
        self.assertTrue(same_value("1,955 ft", 1955))
        self.assertTrue(same_value("2016-08-18", "2016-08-18"))
        self.assertFalse(same_value("August 18, 2016", "2016-08-18"))
        self.assertTrue(score_answer({}, [self.casing], "answered", ["220"])["correct"])

    def test_extra_wrong_value_fails(self):
        self.assertFalse(score_answer({}, [self.depth], "answered", ["1955", "1700"])["correct"])

    def test_no_expected_fact_requires_no_answer(self):
        self.assertTrue(score_answer({}, [], "not_stated", [])["correct"])
        self.assertFalse(score_answer({}, [], "answered", ["42"])["correct"])

    def test_dates_and_numbers_are_normalized_in_code(self):
        self.assertEqual(normalize("18 August 2016"), "2016-08-18")
        self.assertEqual(normalize("August 18th, 2016"), "2016-08-18")
        self.assertEqual(normalize("1,955 ft"), "1955 ft")
        self.assertEqual(normalize("12-1/4"), "12-1/4")


class CitationTests(unittest.TestCase):
    texts = {"d#c0001": "Mud weight was 9.2 ppg.", "d#c0002": "Total depth 1,955 ft MD was reached."}
    hits = ["d#c0001", "d#c0002"]

    def test_correct_citation_is_kept(self):
        answer = {"value": "1955", "chunk": "c0002", "quote": "Total depth 1,955 ft"}
        self.assertEqual(resolve(answer, self.hits, self.texts, "d"), ("d#c0002", "model"))

    def test_wrong_chunk_is_repaired_from_the_quote_or_value(self):
        by_quote = {"value": "1955", "chunk": "c0001", "quote": "1,955 ft MD"}
        self.assertEqual(resolve(by_quote, self.hits, self.texts, "d"), ("d#c0002", "by_quote"))
        by_value = {"value": "9.2", "chunk": "c0099", "quote": "invented"}
        self.assertEqual(resolve(by_value, self.hits, self.texts, "d"), ("d#c0001", "by_value"))

    def test_unsupported_answer_gets_no_citation(self):
        answer = {"value": "3000", "chunk": "c0002", "quote": "3000 ft"}
        self.assertEqual(resolve(answer, self.hits, self.texts, "d"), (None, "unsupported"))


if __name__ == "__main__":
    unittest.main()
