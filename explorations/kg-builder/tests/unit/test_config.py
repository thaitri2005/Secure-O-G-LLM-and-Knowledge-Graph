"""Configuration defaults, overrides, presets, and containment acceptance."""
from __future__ import annotations

import unittest
import yaml
from helpers import PROJECT_ROOT, BASELINE_REPLAY_LOGS, clean_dir, replay_set
from kgbuilder.core.config import ConfigError, PRESETS, edc_dirs, effective_flags, from_resolved, project_path, load_config, load_demo, neo4j_settings, replay_files, load_qa, hipporag_eval_utils


class ConfigTest(unittest.TestCase):
    def test_recall_variant_defaults_validation_and_paths(self):
        cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml")
        self.assertEqual(cfg.extract.guided_mode, "chunk")
        self.assertIsNone(cfg.extract.guided_recall_prompt)
        self.assertFalse(cfg.literals.derive_attributes)
        self.assertIsNone(cfg.literals.lexicon)
        base = ["extract.backend=guided", "extract.guided_prompt=configs/prompts/bsee_guided.txt",
                "canon.schema_path=contracts/ontology/bsee.yaml"]
        for mode in ("chunk", "windows2", "groups4"):
            self.assertEqual(load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", sets=[*base, "extract.guided_mode=" + mode]).extract.guided_mode, mode)
        for invalid in (["extract.guided_mode=other"], ["extract.guided_mode=windows2"],
                        ["extract.guided_recall_prompt=configs/prompts/bsee_guided_recall.txt"],
                        [*base, "extract.guided_mode=groups4", "extract.guided_recall_prompt=configs/prompts/bsee_guided_recall.txt"],
                        [*base, "literals.derive_attributes=true"],
                        ["literals.derive_attributes=true", "literals.lexicon=configs/domains/bsee/bsee_literals.yaml", "canon.schema_path=null"],
                        [*base, "extract.guided_recall_prompt=runs/_test/missing_prompt.txt"],
                        [*base, "literals.lexicon=runs/_test/missing_lexicon.yaml"],
                        [*base, "literals.lexicon=../outside.yaml"]):
            with self.subTest(invalid=invalid), self.assertRaises(ConfigError):
                load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", sets=invalid)
        cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", sets=[*base,
            "extract.guided_recall_prompt=configs/prompts/bsee_guided_recall.txt",
            "literals.derive_attributes=true", "literals.lexicon=configs/domains/bsee/bsee_literals.yaml"])
        self.assertEqual(cfg.extract.guided_recall_prompt, PROJECT_ROOT / "configs/prompts/bsee_guided_recall.txt")
        self.assertEqual(cfg.literals.lexicon, PROJECT_ROOT / "configs/domains/bsee/bsee_literals.yaml")

    def test_corpus_v2_loader(self):
        from kgbuilder.core.config import load_bsee_corpus_v2
        root = clean_dir(PROJECT_ROOT / "runs/_test/recall_config")
        path = root / "corpus.yaml"
        valid = {"source_corpus": "tests/fixtures/bsee/gold_cases/sealed/corpus",
                 "exclude_gold_config": "tests/fixtures/bsee/gold_cases/bsee_gold_test.yaml", "gold_dev": 3, "gold_test": 4}
        path.write_text(yaml.safe_dump(valid), encoding="utf-8")
        cfg = load_bsee_corpus_v2(path)
        self.assertEqual(cfg.seed, 42)
        self.assertEqual(cfg.source_corpus, PROJECT_ROOT / valid["source_corpus"])
        for change in ({"gold_dev": 0}, {"gold_test": 0}, {"extra": 1}, {"source_corpus": "../outside"},
                       {"exclude_gold_config": "runs/_test/recall_config/absent"}):
            path.write_text(yaml.safe_dump({**valid, **change}), encoding="utf-8")
            with self.assertRaises(ConfigError): load_bsee_corpus_v2(path)

    def test_guided_requires_prompt_schema_and_contained_existing_path(self):
        prompt = "extract.guided_prompt=configs/prompts/bsee_guided.txt"
        self.assertIsNone(load_config(self.showcase).extract.guided_prompt)
        cfg = load_config(self.showcase, sets=["extract.backend=guided", prompt])
        self.assertEqual(cfg.extract.backend, "guided")
        self.assertEqual(cfg.extract.guided_prompt, PROJECT_ROOT / "configs/prompts/bsee_guided.txt")
        self.assertEqual(from_resolved(cfg.model_dump(mode="json")), cfg)
        for overrides in (["extract.backend=guided"],
                          ["extract.backend=guided", prompt, "canon.schema_path=null"],
                          ["extract.backend=guided", "extract.guided_prompt=.cache/tmp/missing_guided.txt"],
                          ["extract.backend=guided", "extract.guided_prompt=../outside.txt"]):
            with self.subTest(overrides=overrides), self.assertRaises(ConfigError):
                load_config(self.showcase, sets=overrides)

    def test_judge_versions(self):
        cfg = load_config(self.showcase)
        self.assertEqual((cfg.judge.version, cfg.judge.scope, cfg.judge.max_tokens), ("v2", "risky", 32))
        for version in ("v1", "v1_reparse", "v2"):
            self.assertEqual(load_config(self.showcase, sets=["judge.version=" + version]).judge.version, version)
        for value in ("judge.version=unknown", "judge.scope=unknown"):
            with self.assertRaises(ConfigError):
                load_config(self.showcase, sets=[value])

    def test_qa_window_grounding_modes(self):
        path = PROJECT_ROOT / "configs/experiments/twowiki10_qa.yaml"
        cfg = load_qa(path)
        self.assertEqual((cfg.seed_linking, cfg.fact_order), ("exact", "confidence"))
        cfg = load_qa(path, sets=["qa.seed_linking=robust", "qa.fact_order=relevance"])
        self.assertEqual((cfg.seed_linking, cfg.fact_order), ("robust", "relevance"))
        with self.assertRaises(ConfigError):
            load_qa(path, sets=["qa.seed_linking=unknown"])

    def test_ground_and_number_guard(self):
        cfg = load_config(self.showcase)
        self.assertEqual(cfg.ground.mode, "window")
        self.assertTrue(cfg.resolve.number_guard)
        self.assertEqual(cfg.validate_.mode, "soft")
        self.assertEqual(load_config(self.showcase, sets=["ground.mode=window"]).ground.mode, "window")
        with self.assertRaises(ConfigError):
            load_config(self.showcase, sets=["ground.mode=paragraph"])

    def test_plan_cache(self):
        self.assertEqual(load_config(self.showcase, sets=["llm.cache=plan"]).llm.cache, "plan")
        with self.assertRaises(ConfigError):
            load_config(self.showcase, sets=["llm.cache=unknown"])
        with self.assertRaisesRegex(ConfigError, "requires a replay log"):
            load_config(self.showcase, sets=["llm.cache=plan", "llm.replay_logs=[]",
                                           "llm.cache_path=.cache/tmp/tests/config/missing_plan_cache.jsonl"])

    def test_pinned_replay_files(self):
        cfg = load_config(self.showcase, sets=[replay_set()[1]])
        files = replay_files(cfg)
        self.assertEqual(files, sorted((PROJECT_ROOT / name).resolve() for name in BASELINE_REPLAY_LOGS))
        self.assertTrue(all(path.is_file() for path in files))
        self.assertTrue({"schema_induction_ablation_sentence.jsonl", "twowiki10_kggen_qa.jsonl"}.isdisjoint(p.name for p in files))

    def test_qa_output_overlap(self):
        from kgbuilder.core.config import check_qa_out
        qa = load_qa(PROJECT_ROOT / "configs/experiments/twowiki10_qa.yaml")
        check_qa_out(PROJECT_ROOT / "runs/reference/twowiki10_sentence_grounding/qa", qa)
        graph = next(iter(qa.graphs.values()))
        check_qa_out(graph / "qa", qa)
        for out in (PROJECT_ROOT / "runs/reference/twowiki10_sentence_grounding", graph):
            with self.subTest(out=out), self.assertRaisesRegex(ConfigError, "qa.graphs."):
                check_qa_out(out, qa)

    def test_ablation_config(self):
        from kgbuilder.core.config import load_ablation
        abl = load_ablation(PROJECT_ROOT / "configs/experiments/ablation_sentence_grounding.yaml")
        self.assertTrue(all(r.config.is_file() for r in abl.runs))
        self.assertEqual(abl.levels, [f"A{i}" for i in range(6)])
        path = self.tmp / "ablation_sentence_grounding.yaml"
        body = abl.model_dump(mode="json")
        for changed in [{**body, "levels": ["A6"]}, {**body, "induce": [{"label": "bad", "induce_dir": "tests/fixtures"}]}]:
            path.write_text(yaml.safe_dump({"ablation": changed}), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_ablation(path)

    def test_induce(self):
        from kgbuilder.core.config import autoschemakg_prompts
        self.assertEqual(load_config(self.showcase).induce.max_entities, 50)
        with self.assertRaisesRegex(ConfigError, "induce.max_entities"):
            load_config(self.showcase, sets=["induce.max_entities=-1"])
        self.assertTrue(autoschemakg_prompts().is_file())
        cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase_noschema.yaml")
        self.assertIsNone(cfg.canon.schema_path)
        self.assertEqual(cfg.extract.backend, "kggen")

    def test_validate_alias(self):
        from kgbuilder.core.config import PipelineConfig
        self.assertNotIn("validate", PipelineConfig.model_fields)
        self.assertEqual(PipelineConfig.model_fields["validate_"].alias, "validate")
        self.assertEqual(load_config(self.showcase, sets=["validate.min_grounding=exact"]).validate_.min_grounding, "exact")
        cfg = load_config(self.showcase)
        data = cfg.model_dump(mode="json")
        self.assertIn("validate", data)
        self.assertNotIn("validate_", data)
        self.assertEqual(from_resolved(data), cfg)
        data["validate_"] = data.pop("validate")
        with self.assertRaisesRegex(ConfigError, "validate_"):
            from_resolved(data)

    def test_qa_config(self):
        source = PROJECT_ROOT / "configs/experiments/twowiki10_qa.yaml"
        qa = load_qa(source)
        self.assertEqual((qa.name, qa.limit, list(qa.graphs), qa.k, qa.modes),
                         ("twowiki10_qa", 10, ["A0", "A1", "A4"], 5, ["text", "graph", "hybrid"]))
        for item, field in [("qa.k=0", "k"), ("qa.bogus=1", "qa.bogus"), ("llm.model=x", "llm.model"),
                            ("qa.modes=[text, text]", "modes"), ("qa.graphs={}", "graphs"),
                            ("qa.graphs={A0: tests/fixtures}", "qa.graphs.A0"),
                            ("qa.graphs={A0: runs}", "qa.graphs.A0"), ("qa.k=[", "qa.k"),
                            ("qa.questions=null", "qa.questions"), ("qa.graphs={A0: null}", "qa.graphs.A0")]:
            with self.subTest(item=item), self.assertRaisesRegex(ConfigError, field):
                load_qa(source, [item])
        minimal = self.tmp / "minimal.yaml"
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        del raw["qa"]["k"]
        del raw["qa"]["seed_linking"]
        del raw["qa"]["fact_order"]
        minimal.write_text(yaml.safe_dump(raw), encoding="utf-8")
        self.assertEqual(load_qa(minimal, ["qa.k=3"]).k, 3)
        self.assertEqual((load_qa(minimal).seed_linking, load_qa(minimal).fact_order), ("robust", "relevance"))
        for raw in [[], {"qa": []}, {}]:
            minimal.write_text(yaml.safe_dump(raw), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "qa: expected a mapping"):
                load_qa(minimal)
        cfg = load_config(PROJECT_ROOT / "configs/experiments/twowiki10.yaml")
        self.assertEqual((cfg.corpus.format, cfg.corpus.limit, cfg.extract.backend, cfg.canon.schema_path, cfg.canon.max_minutes),
                         ("wiki_corpus_json", 24, "auto", None, 120))
        self.assertEqual(load_demo(PROJECT_ROOT / "configs/experiments/twowiki10_demo.yaml").levels, ["A0", "A1", "A4"])
        self.assertTrue(hipporag_eval_utils().is_file())

    def test_neo4j_settings(self):
        self.assertEqual(neo4j_settings().model_dump(), {"uri": "bolt://127.0.0.1:7687", "user": "neo4j",
                                                       "database": "neo4j", "batch_size": 500})
        self.assertEqual(neo4j_settings(["neo4j.batch_size=10"]).batch_size, 10)
        self.assertEqual(neo4j_settings().batch_size, 500)
        for item, key in [("neo4j.uri=bolt://192.168.1.5:7687", "neo4j.uri"), ("llm.model=x", "llm.model"),
                          ("neo4j.batch_size=0", "batch_size"), ("neo4j.password=x", "neo4j.password"),
                          ("neo4j.uri=[", "neo4j.uri"), ("neo4j.user", "neo4j.user")]:
            with self.subTest(item=item), self.assertRaisesRegex(ConfigError, key):
                neo4j_settings([item])

    def setUp(self):
        self.tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/config" / self._testMethodName)
        self.showcase = PROJECT_ROOT / "configs/experiments/showcase.yaml"

    def test_defaults_and_shipped(self):
        cfg = load_config(self.showcase)
        self.assertEqual(cfg.llm.max_tokens, 2048)
        self.assertEqual(cfg.llm.cache, "readwrite")
        self.assertEqual((cfg.llm.profile, cfg.llm.base_url, cfg.llm.model, cfg.llm.request_mode),
                         ("lmstudio", "http://127.0.0.1:1234/v1", "qwen3.6-35b-a3b", "completions_chatml"))
        self.assertEqual(cfg.extract.backend, "kggen")
        self.assertEqual(cfg.extract.route_tau, .33)
        self.assertEqual(cfg.canon.max_minutes, 20)
        recorded = ["webnlg10_edc.jsonl", "mine3_kggen.jsonl", "showcase_kggen.jsonl", "showcase_webnlg10_kggen.jsonl", "twowiki10_kggen_qa.jsonl", "schema_induction_ablation_sentence.jsonl", "ablation_window_grounding.jsonl"]
        if (PROJECT_ROOT / "data/fixtures/llm/bsee_text_test_subset_v1_base.jsonl").is_file():
            recorded.append("bsee_text_test_subset_v1_base.jsonl")
        if (PROJECT_ROOT / "data/fixtures/llm/bsee_text_dev_v1_base.jsonl").is_file():
            recorded.append("bsee_text_dev_v1_base.jsonl")
        if (PROJECT_ROOT / "data/fixtures/llm/bsee_text_dev_v1_guided.jsonl").is_file():
            recorded.append("bsee_text_dev_v1_guided.jsonl")
        if (PROJECT_ROOT / "data/fixtures/llm/bsee_text_test_subset_v1_guided.jsonl").is_file():
            recorded.append("bsee_text_test_subset_v1_guided.jsonl")
        if (PROJECT_ROOT / "data/fixtures/llm/bsee_text_dev_v2_guided.jsonl").is_file():
            recorded.append("bsee_text_dev_v2_guided.jsonl")
        for variant in ("windows", "groups", "recall"):
            filename = f"bsee_text_dev_v2_guided_{variant}.jsonl"
            self.assertTrue((PROJECT_ROOT / "data/fixtures/llm" / filename).is_file())
            recorded.append(filename)
        for variant in ("guided", "guided_recall"):
            filename = f"bsee_text_test_v2_{variant}.jsonl"
            self.assertTrue((PROJECT_ROOT / "data/fixtures/llm" / filename).is_file())
            recorded.append(filename)
        self.assertEqual(replay_files(cfg), sorted(PROJECT_ROOT / "data/fixtures/llm" / name for name in recorded))
        self.assertTrue(all(x.is_dir() for x in edc_dirs(cfg)))
        self.assertEqual(from_resolved(cfg.model_dump(mode="json")), cfg)
        web = load_config(PROJECT_ROOT / "configs/experiments/webnlg10.yaml")
        self.assertEqual(web.corpus.limit, 10)
        self.assertEqual(web.extract.backend, "edc")
        self.assertEqual(web.canon.max_minutes, 20)
        demo = load_demo(PROJECT_ROOT / "configs/experiments/demo.yaml")
        self.assertEqual(demo.levels, ["A0", "A4"])
        self.assertEqual(len(demo.runs), 2)

    def test_presets(self):
        for i in range(6):
            self.assertEqual(sum(PRESETS[f"A{i}"].values()), i)
        for level in ["A0", "A1", "A2", "A3", "A4", "A5"]:
            cfg = load_config(self.showcase, ablation=level)
            self.assertEqual(effective_flags(cfg), PRESETS[level])
        with self.assertRaises(ConfigError):
            load_config(self.showcase, ablation="A6")

    def test_flags_and_set(self):
        cfg = load_config(self.showcase, sets=["chunk.max_chars=500", "flags.canon=false"], mock=True)
        self.assertEqual(cfg.chunk.max_chars, 500)
        self.assertEqual(cfg.llm.cache, "readonly")
        with self.assertLogs("kgb", "WARNING") as logged:
            self.assertFalse(effective_flags(cfg)["canon"])
        self.assertIn("override preset", logged.output[0])

    def test_urls_and_paths_rejected(self):
        for key, value in [("llm.base_url", "http://api.openai.com/v1"),
                           ("llm.base_url", "http://192.168.1.5:1234/v1"),
                           ("neo4j.uri", "bolt://192.168.1.5:7687"),
                           ("corpus.path", "C:/Windows/Temp/x"),
                           ("llm.replay_logs", "[C:/Windows/Temp/*.jsonl]")]:
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ConfigError, key):
                load_config(self.showcase, sets=[f"{key}={value}"])
        with self.assertRaisesRegex(ConfigError, "outside project"):
            project_path("../outside", "test", False)

    def test_invalid_values(self):
        with self.assertRaisesRegex(ConfigError, "extract.route_tau"):
            load_config(self.showcase, sets=["extract.route_tau=1.5"])
        with self.assertRaisesRegex(ConfigError, "extract.backend"):
            load_config(self.showcase, sets=["extract.backend=bogus"])
        for item, expected in [("resolve.method=lm", "not in this milestone"),
                               ("chunk.max_chars=1", "chunk.max_chars"),
                               ("llm.replay_logs=[]", None), ("bad.key=1", "bad.key")]:
            if expected is None:
                with self.assertRaises(ConfigError):
                    load_config(self.showcase, sets=[item, "llm.cache_path=.cache/tmp/tests/config/missing.jsonl"], mock=True)
            else:
                with self.assertRaisesRegex(ConfigError, expected):
                    load_config(self.showcase, sets=[item])
        cfg = load_config(self.showcase)
        with self.assertRaisesRegex(ConfigError, "ablation"):
            from_resolved({**cfg.model_dump(mode="json"), "ablation": "A9"})

    def test_invalid_demo(self):
        for levels in [["A0", "A6"], ["A0", "A0"], []]:
            path = self.tmp / "demo.yaml"
            path.write_text(yaml.safe_dump({"demo": {"name": "test", "levels": levels,
                                                     "runs": ["configs/experiments/showcase.yaml"]}}), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_demo(path)

    def test_profiles_and_explicit_overrides(self):
        cfg = load_config(self.showcase, sets=["llm.profile=vllm"])
        self.assertEqual((cfg.llm.base_url, cfg.llm.model, cfg.llm.request_mode),
                         ("http://127.0.0.1:8000/v1", "qwen3.6-35b-a3b-fp8", "completions_chatml"))
        self.assertEqual(from_resolved(cfg.model_dump(mode="json")), cfg)
        explicit = load_config(self.showcase, sets=["llm.profile=vllm", "llm.model=x", "llm.base_url=http://localhost:8011/v1", "llm.request_mode=chat_nothink"])
        self.assertEqual((explicit.llm.model, explicit.llm.base_url, explicit.llm.request_mode), ("x", "http://localhost:8011/v1", "chat_nothink"))
        with self.assertRaisesRegex(ConfigError, "llm.base_url"):
            load_config(self.showcase, sets=["llm.profile=vllm", "llm.base_url=http://10.0.0.5:8000/v1"])
        with self.assertRaisesRegex(ConfigError, "llm.profile"):
            load_config(self.showcase, sets=["llm.profile=openai"])


if __name__ == "__main__":
    unittest.main()
