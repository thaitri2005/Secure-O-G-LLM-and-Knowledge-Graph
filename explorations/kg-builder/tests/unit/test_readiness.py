"""Metadata-only readiness checks with injected GET; no preflight or HTTP."""
from __future__ import annotations

import unittest

from helpers import PROJECT_ROOT
from kgbuilder.build import pipeline
from kgbuilder.core.config import KgbError, load_config


class ReadinessTest(unittest.TestCase):
    def setUp(self):
        self.source = PROJECT_ROOT / "configs/experiments/showcase.yaml"
        self.cfg = load_config(self.source)
        self.urls = []

    def get(self, detail, present=True):
        def recording_get(url):
            self.urls.append(url)
            if url.endswith("/models"):
                return {"data": [{"id": self.cfg.llm.model}] if present else []}
            return detail
        return recording_get

    def test_loaded(self):
        result = pipeline.model_ready(self.cfg, get=self.get({"state": "loaded", "loaded_context_length": 8192}))
        self.assertEqual(result, {"context": 8192, "state": "loaded", "warnings": []})
        self.assertEqual(self.urls, [self.cfg.llm.base_url + "/models",
                         self.cfg.llm.base_url[:-3] + "/api/v0/models/" + self.cfg.llm.model])
        self.assertFalse(any("parallel" in key for key in result))
        self.assertEqual(pipeline.LLM_STAGES, ("extract", "canon", "judge"))

    def test_small_context(self):
        with self.assertRaises(KgbError) as caught:
            pipeline.model_ready(self.cfg, get=self.get({"state": "loaded", "loaded_context_length": 4096}))
        self.assertEqual(caught.exception.code, 3)
        self.assertIn("lms load qwen3.6-35b-a3b -c 8192 --parallel 2 -y", str(caught.exception))

    def test_missing_metadata(self):
        self.assertEqual(pipeline.model_ready(self.cfg, get=self.get({})),
                         {"context": None, "state": None, "warnings": ["WARNING: không kiểm được context length"]})

    def test_model_absent(self):
        with self.assertRaises(KgbError) as caught:
            pipeline.model_ready(self.cfg, get=self.get({}, present=False))
        self.assertEqual(caught.exception.code, 3)
        self.assertIn("model is not loaded", str(caught.exception))
        self.assertEqual(len(self.urls), 1)

    def test_readonly(self):
        self.assertEqual(pipeline.model_ready(load_config(self.source, mock=True), get=self.get({})),
                         {"context": None, "state": None, "warnings": []})
        self.assertEqual(self.urls, [])

    def test_plan(self):
        self.assertEqual(pipeline.model_ready(load_config(self.source, sets=["llm.cache=plan"]), get=self.get({})),
                         {"context": None, "state": None, "warnings": []})
        self.assertEqual(self.urls, [])

