"""Validated pipeline configuration, ablation presets, and project path policy."""
from __future__ import annotations

import copy
import glob
import logging
import re
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from kgbuilder.core.project import PROJECT_ROOT, require_loopback_url

LOG = logging.getLogger("kgb")

LLM_PROFILES = {
    "lmstudio": {"base_url": "http://127.0.0.1:1234/v1", "model": "qwen3.6-35b-a3b", "request_mode": "completions_chatml", "api_key_env": "LMSTUDIO_API_KEY"},
    "vllm": {"base_url": "http://127.0.0.1:8000/v1", "model": "qwen3.6-35b-a3b-fp8", "request_mode": "completions_chatml", "api_key_env": "KGB_VLLM_API_KEY"},
}


class KgbError(Exception):
    """An expected product error with a CLI exit code."""
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


class ConfigError(KgbError):
    """Configuration or input error (exit code 2)."""
    def __init__(self, msg: str):
        super().__init__(2, msg)


PRESETS: dict[str, dict[str, bool]] = {
    "A0": {"resolve": False, "canon": False, "temporal": False, "validate": False, "judge": False},
    "A1": {"resolve": True, "canon": False, "temporal": False, "validate": False, "judge": False},
    "A2": {"resolve": True, "canon": True, "temporal": False, "validate": False, "judge": False},
    "A3": {"resolve": True, "canon": True, "temporal": True, "validate": False, "judge": False},
    "A4": {"resolve": True, "canon": True, "temporal": True, "validate": True, "judge": False},
    "A5": {"resolve": True, "canon": True, "temporal": True, "validate": True, "judge": True},
}

_BASE = {
    "run": {},
    "corpus": {"format": "jsonl", "limit": None},
    "chunk": {"max_chars": 2000},
    "llm": {"profile": "lmstudio", "base_url": None, "model": None, "request_mode": None, "max_tokens": 2048, "timeout_s": 600, "max_concurrency": 2, "min_context": 8192, "cache": "readwrite", "cache_path": ".cache/kgb/llm_cache.jsonl", "replay_logs": ["data/fixtures/llm/*.jsonl"]},
    "extract": {"max_failed_chunk_ratio": 0.2, "backend": "kggen", "route_tau": 0.33, "guided_prompt": None, "guided_mode": "chunk", "guided_recall_prompt": None},
    "literals": {"derive_attributes": False, "lexicon": None},
    "ground": {"mode": "window"},
    "resolve": {"method": "semhash", "alias_rules": True, "semhash_threshold": 0.95, "embedder": "sentence-transformers/all-MiniLM-L6-v2", "number_guard": True},
    "canon": {"schema_path": None, "few_shot": "example", "embedder": "sentence-transformers/all-MiniLM-L6-v2", "edc_python": ".venvs/edc/Scripts/python.exe", "max_minutes": 60},
    "validate": {"min_grounding": "partial", "mode": "soft"},
    "judge": {"max_tokens": 32, "version": "v2", "scope": "risky"},
    "induce": {"max_entities": 50, "max_concepts": 5, "max_tokens": 64, "min_support": 1, "max_relations": 100},
    "eval": {"webnlg_reference": None, "showcase_gold_dir": None, "showcase_queries": None},
    "neo4j": {"uri": "bolt://127.0.0.1:7687", "user": "neo4j", "database": "neo4j", "batch_size": 500},
    "ablation": "A4", "flags": {},
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemberSpec(BaseModel):
    """Explicit, independently verified columns of a local archive member."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    encoding: Literal["utf-8", "cp1252"]
    header: list[str] | None = None
    positional: list[str] | None = None
    allow_columns: list[str]
    deny_columns: list[str] = []
    dictionary_ref: str
    dictionary_names: dict[str, str] = {}
    status_codes: dict[str, list[str]] = {}

    @model_validator(mode="after")
    def _columns(self):
        if (self.header is None) == (self.positional is None):
            raise ValueError("exactly one of header and positional is required")
        columns = self.header if self.header is not None else self.positional
        named = [c for c in columns if c]
        if len(named) != len(set(named)) or not set(self.allow_columns) <= set(named):
            raise ValueError("duplicate or unknown mapped columns")
        if set(self.allow_columns) & (set(self.deny_columns) | {"CONTACT_NAME", "PHONE_NUMBER"}):
            raise ValueError("denylisted column cannot be mapped")
        if not set(self.status_codes) <= set(self.allow_columns):
            raise ValueError("status code map requires an allowlisted column")
        return self


class ArchiveSpec(BaseModel):
    """Local ZIP inventory; an empty mapping registers bytes only."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    required: bool
    region: str | None = None
    members: dict[str, MemberSpec] = {}


class BseeSourceConfig(BaseModel):
    """Immutable offline BSEE source registration settings."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    snapshot: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    receipt: str
    archives: dict[str, ArchiveSpec]
    dictionaries: list[str]
    max_expanded_bytes: int = Field(gt=0, default=2_000_000_000)


def load_bsee_sources(path: Path) -> BseeSourceConfig:
    """Load standalone source settings without changing pipeline defaults."""
    source = project_path(path, "bsee sources", True)
    try:
        cfg = BseeSourceConfig.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError("invalid BSEE source configuration") from exc
    project_path(cfg.receipt, "receipt", True)
    return cfg


class DomainTablesConfig(BaseModel):
    """Standalone bounded-memory table build configuration."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_manifest: Path
    regions: list[Literal["gom", "pacific", "alaska"]]
    scope: Literal["core", "extended"]
    sqlite_cache_mib: int = Field(default=64, ge=1, le=64)


class BseeCorpusConfig(BaseModel):
    """Frozen eligibility and sampling policy for single-chunk EOR documents."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_manifest: Path
    tables: Path
    source_types: list[Literal["eor"]] = ["eor"]
    seed: int = 42
    min_chars: int = Field(default=200, ge=1)
    max_chars: int = Field(default=2000, le=2000)
    max_per_api10: Literal[1] = 1
    gold_dev: int = Field(default=25, ge=0)
    gold_test: int = Field(default=75, ge=0)
    test_subset: int = Field(default=50, ge=0)
    strata: list[Literal["EOR_OPERATION_CD"]] = ["EOR_OPERATION_CD"]
    exclude_sn_eor: list[str] = ["-119604", "-120850", "-112992"]

    @model_validator(mode="after")
    def _window(self):
        if self.min_chars > self.max_chars:
            raise ValueError("invalid length window")
        return self


class BseeCorpusV2Config(BaseModel):
    """Select fresh gold documents from a frozen, already screened corpus."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_corpus: Path
    exclude_gold_config: Path
    seed: int = 42
    gold_dev: int = Field(ge=1)
    gold_test: int = Field(ge=1)


def load_bsee_corpus_v2(path: Path) -> BseeCorpusV2Config:
    """Resolve both existing inputs inside the project without rebuilding eligibility."""
    try:
        cfg = BseeCorpusV2Config.model_validate(yaml.safe_load(project_path(path, "corpus config", True).read_text(encoding="utf-8")))
        return cfg.model_copy(update={key: project_path(getattr(cfg, key), key, True)
                                      for key in ("source_corpus", "exclude_gold_config")})
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError("invalid BSEE corpus v2 configuration") from exc


class WellEvalConfig(BaseModel):
    """Predeclared evaluation policy; no values learned from the corpus."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    tolerance: dict[str, float]
    well_aliases: list[str]
    well_name_pattern: str
    generic_heads: list[str]
    field_relations: dict[str, str]
    status_lexicon: dict[str, list[str]]
    not_mapped: list[str]
    insufficient: int = 5
    bootstrap: dict[str, int]


def load_well_eval(path: Path) -> WellEvalConfig:
    """Read a strict evaluation policy from a contained YAML file."""
    try:
        return WellEvalConfig.model_validate(yaml.safe_load(project_path(path, "evaluation config", True).read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError("invalid well evaluation configuration") from exc


def load_bsee_corpus(path: Path) -> BseeCorpusConfig:
    """Load a corpus policy with project-contained sources and bundle."""
    try:
        cfg = BseeCorpusConfig.model_validate(yaml.safe_load(project_path(path, "corpus config", True).read_text(encoding="utf-8")))
        return cfg.model_copy(update={"source_manifest": project_path(cfg.source_manifest, "sources", True),
                                      "tables": project_path(cfg.tables, "tables", True)})
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError("invalid BSEE corpus configuration") from exc


def load_domain_tables(path: Path) -> DomainTablesConfig:
    """Load table configuration and resolve its registered source manifest."""
    try:
        body = yaml.safe_load(project_path(path, "tables config", True).read_text(encoding="utf-8"))
        cfg = DomainTablesConfig.model_validate(body)
        return cfg.model_copy(update={"source_manifest": project_path(cfg.source_manifest, "source manifest", True)})
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError("invalid domain tables configuration") from exc


class Run(Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9_.\-]{1,64}$")


class Corpus(Strict):
    path: Path
    format: Literal["jsonl", "webnlg_txt", "mine_jsonl", "wiki_corpus_json"] = "jsonl"
    limit: int | None = Field(default=None, ge=1, le=100000)


class Chunk(Strict):
    max_chars: int = Field(default=2000, ge=200, le=20000)


class Llm(Strict):
    profile: Literal["lmstudio", "vllm"] = "lmstudio"
    base_url: str
    model: str = Field(min_length=1, max_length=128)
    request_mode: Literal["completions_chatml", "chat_nothink"]
    max_tokens: int = Field(default=2048, ge=16, le=8192)
    timeout_s: int = Field(default=600, ge=30, le=1800)
    max_concurrency: int = Field(default=2, ge=1, le=4)
    min_context: int = Field(default=8192, ge=2048, le=262144)
    cache: Literal["off", "readwrite", "readonly", "plan"] = "readwrite"
    cache_path: Path = Path(".cache/kgb/llm_cache.jsonl")
    replay_logs: list[str] = list(_BASE["llm"]["replay_logs"])

    @model_validator(mode="before")
    @classmethod
    def _profile_defaults(cls, data):
        if isinstance(data, dict):
            data = dict(data)
            defaults = LLM_PROFILES.get(data.get("profile", "lmstudio"), {})
            for key in ("base_url", "model", "request_mode"):
                if data.get(key) is None and key in defaults: data[key] = defaults[key]
        return data


class Extract(Strict):
    max_failed_chunk_ratio: float = Field(default=.2, ge=0, le=1)
    backend: Literal["kggen", "edc", "auto", "guided"] = "kggen"
    guided_prompt: Path | None = None
    guided_mode: Literal["chunk", "windows2", "groups4"] = "chunk"
    guided_recall_prompt: Path | None = None
    route_tau: float = Field(default=0.33, ge=0, le=1)


class Literals(Strict):
    """Opt-in casing-size derivation from extracted tubular surfaces."""
    derive_attributes: bool = False
    lexicon: Path | None = None


class Ground(Strict):
    mode: Literal["sentence", "window"] = "window"


class Resolve(Strict):
    number_guard: bool = True
    method: str = "semhash"
    alias_rules: bool = True
    semhash_threshold: float = Field(default=.95, ge=.5, le=1)
    embedder: str = "sentence-transformers/all-MiniLM-L6-v2"

    @field_validator("method")
    @classmethod
    def _method(cls, value):
        if value != "semhash": raise ValueError("not in this milestone")
        return value


class Canon(Strict):
    schema_path: Path | None = None
    few_shot: Literal["example", "webnlg", "rebel", "wiki-nre"] = "example"
    embedder: str = "sentence-transformers/all-MiniLM-L6-v2"
    edc_python: Path = Path(".venvs/edc/Scripts/python.exe")
    max_minutes: int = Field(default=60, ge=1, le=600)


class Validate(Strict):
    mode: Literal["strict", "soft"] = "soft"
    min_grounding: Literal["exact", "partial"] = "partial"


class Judge(Strict):
    version: Literal["v1", "v1_reparse", "v2"] = "v2"
    scope: Literal["risky", "all"] = "risky"
    max_tokens: int = Field(default=32, ge=4, le=64)


class Eval(Strict):
    webnlg_reference: Path | None = None
    showcase_gold_dir: Path | None = None
    showcase_queries: Path | None = None


class Induce(Strict):
    max_entities: int = Field(default=50, ge=0, le=2000)
    max_concepts: int = Field(default=5, ge=1, le=10)
    max_tokens: int = Field(default=64, ge=8, le=256)
    min_support: int = Field(default=1, ge=1, le=100)
    max_relations: int = Field(default=100, ge=1, le=1000)


class Neo4j(Strict):
    uri: str = "bolt://127.0.0.1:7687"
    user: str = "neo4j"
    database: str = "neo4j"
    batch_size: int = Field(default=500, ge=1, le=10000)


class PipelineConfig(Strict):
    model_config = ConfigDict(extra="forbid", serialize_by_alias=True)
    run: Run
    corpus: Corpus
    chunk: Chunk = Chunk()
    llm: Llm = Llm()
    extract: Extract = Extract()
    literals: Literals = Literals()
    ground: Ground = Ground()
    resolve: Resolve = Resolve()
    canon: Canon = Canon()
    validate_: Validate = Field(default=Validate(), alias="validate")
    judge: Judge = Judge()
    induce: Induce = Induce()
    eval: Eval = Eval()
    neo4j: Neo4j = Neo4j()
    ablation: str = "A4"
    flags: dict[str, bool] = {}

    @field_validator("ablation")
    @classmethod
    def _ablation(cls, value):
        if value not in PRESETS: raise ValueError("ablation must be A0..A5")
        return value

    @field_validator("flags")
    @classmethod
    def _flags(cls, value):
        unknown = set(value) - set(PRESETS["A4"])
        if unknown: raise ValueError(f"unknown flags: {sorted(unknown)}")
        return value

    @model_validator(mode="after")
    def _urls(self):
        if (self.extract.guided_mode != "chunk" or self.extract.guided_recall_prompt is not None) and self.extract.backend != "guided":
            raise ValueError("guided variants require extract.backend guided")
        if self.extract.guided_recall_prompt is not None and self.extract.guided_mode != "chunk":
            raise ValueError("extract.guided_recall_prompt requires guided_mode chunk")
        if self.literals.derive_attributes and (self.literals.lexicon is None or self.canon.schema_path is None):
            raise ValueError("literals.derive_attributes requires literals.lexicon and canon.schema_path")
        if self.extract.backend == "guided" and (self.extract.guided_prompt is None or self.canon.schema_path is None):
            raise ValueError("extract.backend guided requires extract.guided_prompt and canon.schema_path")
        for key, url, schemes in [("llm.base_url", self.llm.base_url, ("http",)), ("neo4j.uri", self.neo4j.uri, ("bolt", "neo4j"))]:
            try: require_loopback_url(url, key, schemes)
            except ValueError as exc: raise ValueError(str(exc)) from exc
        if not urlparse(self.llm.base_url).path.rstrip("/").endswith("/v1"):
            raise ValueError("llm.base_url: path must end with /v1")
        return self


def api_key_env(cfg: PipelineConfig) -> str:
    """Return the profile's environment variable name, never its value."""
    return LLM_PROFILES[cfg.llm.profile]["api_key_env"]


def neo4j_settings(sets: list[str] = ()) -> Neo4j:
    """Load only Neo4j defaults and overrides, independent of a run manifest."""
    values = copy.deepcopy(_BASE["neo4j"])
    for item in sets:
        key, separator, value = item.partition("=")
        if not separator or key not in {"neo4j." + name for name in values}:
            raise ConfigError(f"{key}: expected neo4j.<uri|user|database|batch_size>=value")
        try:
            values[key.split(".")[1]] = yaml.safe_load(value)
        except yaml.YAMLError as exc:
            raise ConfigError(f"{key}: {exc}") from exc
    try:
        settings = Neo4j.model_validate(values)
    except ValidationError as exc:
        raise ConfigError("neo4j: " + str(exc).replace("\n", "; ")) from exc
    try:
        require_loopback_url(settings.uri, "neo4j.uri", ("bolt", "neo4j"))
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return settings


def _deep_merge(left: dict, right: dict) -> dict:
    out = copy.deepcopy(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict): out[key] = _deep_merge(out[key], value)
        else: out[key] = value
    return out


def project_path(value: str | Path, key: str, must_exist: bool) -> Path:
    """Resolve a path under PROJECT_ROOT and optionally require it to exist."""
    path = Path(value)
    path = (PROJECT_ROOT / path) if not path.is_absolute() else path
    path = path.resolve()
    try: path.relative_to(PROJECT_ROOT)
    except ValueError as exc: raise ConfigError(f"{key}: path outside project: {path}") from exc
    if must_exist and not path.exists(): raise ConfigError(f"{key}: file does not exist: {path}")
    return path


def _set_value(data: dict, dotted: str, value: Any) -> None:
    bits = dotted.split("."); target = data
    for bit in bits[:-1]:
        if bit not in target or not isinstance(target[bit], dict): raise ConfigError(f"{dotted}: unknown key")
        target = target[bit]
    if bits[-1] not in target and not (bits[0] == "flags" and bits[-1] in PRESETS["A4"]):
        raise ConfigError(f"{dotted}: unknown key")
    target[bits[-1]] = value


def _resolved_paths(data: dict) -> dict:
    data = copy.deepcopy(data)
    for section, key, exists in [("corpus", "path", True), ("extract", "guided_prompt", True), ("extract", "guided_recall_prompt", True), ("literals", "lexicon", True), ("canon", "schema_path", True), ("canon", "edc_python", False), ("eval", "webnlg_reference", True), ("eval", "showcase_gold_dir", True), ("eval", "showcase_queries", True), ("llm", "cache_path", False)]:
        section_data = data.get(section, {})
        if not isinstance(section_data, dict):
            raise ConfigError(f"{section}: expected a mapping")
        value = section_data.get(key)
        if value is not None: data[section][key] = str(project_path(value, f"{section}.{key}", exists))
    return data


def load_config(path: Path, ablation: str | None = None, sets: list[str] = (), mock: bool = False) -> PipelineConfig:
    """Load YAML, apply overrides, resolve project paths, and validate it."""
    source = project_path(path, "config", True)
    try: raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc: raise ConfigError(f"config: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("config: expected a mapping")
    if "run" not in raw or "corpus" not in raw:
        raise ConfigError("run.name and corpus.path are required")
    data = _deep_merge(_BASE, raw)
    for item in sets:
        if "=" not in item: raise ConfigError(f"--set requires key=value: {item}")
        key, value = item.split("=", 1)
        try: parsed = yaml.safe_load(value)
        except yaml.YAMLError as exc: raise ConfigError(f"{key}: {exc}") from exc
        _set_value(data, key, parsed)
    if ablation is not None: data["ablation"] = ablation
    if mock: data["llm"]["cache"] = "readonly"
    try:
        cfg = PipelineConfig.model_validate(_resolved_paths(data))
    except ValidationError as exc:
        message = str(exc).replace("\n", "; ")
        raise ConfigError(message) from exc
    replay = replay_files(cfg)
    if cfg.llm.cache in ("readonly", "plan") and not replay and not cfg.llm.cache_path.is_file():
        raise ConfigError(f"llm.cache={cfg.llm.cache} requires a replay log or existing cache_path")
    return cfg


def effective_flags(cfg: PipelineConfig) -> dict[str, bool]:
    result = dict(PRESETS[cfg.ablation])
    for key, value in cfg.flags.items():
        LOG.warning("override preset %s=%s", key, value)
        result[key] = value
    return result


def replay_files(cfg: PipelineConfig) -> list[Path]:
    paths = []
    for pattern in cfg.llm.replay_logs:
        path = Path(pattern)
        if not path.is_absolute(): path = PROJECT_ROOT / path
        try: path.resolve().relative_to(PROJECT_ROOT)
        except ValueError as exc: raise ConfigError(f"llm.replay_logs: path outside project: {path}") from exc
        for found in glob.glob(str(path)):
            candidate = project_path(found, "llm.replay_logs", True)
            if candidate.is_file() and candidate not in paths: paths.append(candidate)
    return sorted(paths)


def edc_dirs(cfg: PipelineConfig) -> tuple[Path, Path]:
    few = project_path(f"third_party/edc/few_shot_examples/{cfg.canon.few_shot}", "canon.few_shot", True)
    templates = project_path("third_party/edc/prompt_templates", "canon.templates", True)
    return few, templates


class QaConfig(Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9_.\-]{1,64}$")
    build_config: Path
    questions: Path
    limit: int | None = Field(default=None, ge=1, le=1000)
    graphs: dict[str, Path]
    modes: list[Literal["text", "graph", "hybrid"]] = ["text", "graph", "hybrid"]
    k: int = Field(default=5, ge=1, le=20)
    hops: int = Field(default=2, ge=1, le=3)
    max_seeds: int = Field(default=5, ge=1, le=20)
    max_statements: int = Field(default=20, ge=1, le=100)
    max_tokens: int = Field(default=32, ge=8, le=128)
    embedder: str = "sentence-transformers/all-MiniLM-L6-v2"
    seed_linking: Literal["exact", "robust"] = "robust"
    fact_order: Literal["confidence", "relevance"] = "relevance"

    @field_validator("graphs")
    @classmethod
    def _graphs(cls, value):
        if not 1 <= len(value) <= 5:
            raise ValueError("graphs must contain 1..5 entries")
        for key in value:
            if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,16}", key):
                raise ValueError(f"graphs.{key}: invalid label")
        return value

    @field_validator("modes")
    @classmethod
    def _modes(cls, value):
        if not 1 <= len(value) <= 3 or len(set(value)) != len(value):
            raise ValueError("modes must be unique and contain 1..3 values")
        return value


def check_qa_out(out: Path, qa: QaConfig) -> None:
    """Reject an output tree that could delete a QA input on overwrite."""
    for label, graph in qa.graphs.items():
        if out == graph or graph.is_relative_to(out):
            raise ConfigError(f"out: must not equal or contain qa.graphs.{label} ({graph.relative_to(PROJECT_ROOT).as_posix()})")


def load_qa(path: Path, sets: list[str] = ()) -> QaConfig:
    """Load and validate a QA configuration without reading graph outputs."""
    source = project_path(path, "qa", True)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"qa: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("qa"), dict):
        raise ConfigError("qa: expected a mapping")
    body = copy.deepcopy(raw["qa"])
    for item in sets:
        key, sep, value = item.partition("=")
        if not sep or not key.startswith("qa.") or key[3:] not in QaConfig.model_fields:
            if key.startswith("qa."):
                raise ConfigError(f"{key}: unknown key")
            raise ConfigError(f"{key}: expected qa.<field>=value")
        try:
            body[key[3:]] = yaml.safe_load(value)
        except yaml.YAMLError as exc:
            raise ConfigError(f"{key}: {exc}") from exc
    for key in ("build_config", "questions"):
        if key not in body:
            raise ConfigError(f"qa.{key}: field required")
        if not isinstance(body[key], (str, Path)):
            raise ConfigError(f"qa.{key}: expected a path")
        body[key] = project_path(body[key], f"qa.{key}", True)
    graphs = body.get("graphs")
    if not isinstance(graphs, dict):
        raise ConfigError("qa.graphs: expected a mapping")
    resolved = {}
    root = (PROJECT_ROOT / "runs").resolve()
    for label, value in graphs.items():
        if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9_.\-]{1,16}", label):
            raise ConfigError(f"qa.graphs.{label}: invalid label")
        if not isinstance(value, (str, Path)):
            raise ConfigError(f"qa.graphs.{label}: expected a path")
        p = project_path(value, f"qa.graphs.{label}", False)
        if not p.is_relative_to(root) or p == root:
            raise ConfigError(f"qa.graphs.{label}: must be below runs/")
        resolved[label] = p
    body["graphs"] = resolved
    try:
        return QaConfig.model_validate(body)
    except ValidationError as exc:
        raise ConfigError(str(exc).replace("\n", "; ")) from exc


def hipporag_eval_utils() -> Path:
    """Return the upstream evaluation normalizer file."""
    path = PROJECT_ROOT / "third_party/hipporag/src/hipporag/utils/eval_utils.py"
    if not path.is_file():
        raise KgbError(3, f"missing upstream file {path} (configs/runtime/repos.lock.csv: hipporag)")
    return path


def autoschemakg_prompts() -> Path:
    """Locate the upstream concept templates for read-only AST extraction."""
    path = PROJECT_ROOT / "third_party/autoschemakg/atlas_rag/llm_generator/prompt/triple_extraction_prompt.py"
    if not path.is_file():
        raise KgbError(3, f"missing upstream file {path} (configs/runtime/repos.lock.csv: autoschemakg)")
    return path


def from_resolved(data: dict) -> PipelineConfig:
    try:
        cfg = PipelineConfig.model_validate(_resolved_paths(data))
    except ValidationError as exc: raise ConfigError(str(exc).replace("\n", "; ")) from exc
    replay = replay_files(cfg)
    if cfg.llm.cache in ("readonly", "plan") and not replay and not cfg.llm.cache_path.is_file():
        raise ConfigError(f"llm.cache={cfg.llm.cache} requires a replay log or existing cache_path")
    return cfg


class Baseline(Strict):
    label: str
    eval_txt: Path


class DemoConfig(Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9_.\-]{1,64}$")
    levels: list[str]
    runs: list[Path] = Field(min_length=1, max_length=10)
    baselines: dict[str, Baseline] = {}

    @field_validator("levels")
    @classmethod
    def _levels(cls, values):
        if not 1 <= len(values) <= 6 or len(set(values)) != len(values) or any(x not in PRESETS for x in values):
            raise ValueError("levels must be unique A0..A5 values")
        return values


def load_demo(path: Path) -> DemoConfig:
    source = project_path(path, "demo", True)
    try: raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}; body = raw["demo"]
    except (KeyError, TypeError, yaml.YAMLError, OSError) as exc: raise ConfigError(f"demo: {exc}") from exc
    try:
        body = copy.deepcopy(body)
        body["runs"] = [project_path(p, "demo.runs", True) for p in body.get("runs", [])]
        body["baselines"] = {name: {**value, "eval_txt": project_path(value["eval_txt"], f"demo.baselines.{name}.eval_txt", True)} for name, value in body.get("baselines", {}).items()}
        return DemoConfig.model_validate(body)
    except (ValidationError, KeyError) as exc: raise ConfigError(str(exc).replace("\n", "; ")) from exc


class AblationRun(Strict):
    config: Path
    sets: list[str] = []
    levels: list[str] | None = None

    @field_validator("levels")
    @classmethod
    def _levels(cls, value):
        return DemoConfig._levels(value) if value is not None else None


class AblationQa(Strict):
    config: Path
    run: str
    levels: list[str]
    sets: list[str] = []

    @field_validator("levels")
    @classmethod
    def _levels(cls, value):
        return DemoConfig._levels(value)


class AblationInduce(Strict):
    label: str = Field(pattern=r"^[A-Za-z0-9_.\-]{1,32}$")
    induce_dir: Path
    pass2_run: Path | None = None


class AblationConfig(Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9_.\-]{1,64}$")
    levels: list[str]
    runs: list[AblationRun] = Field(min_length=1, max_length=10)
    baselines: dict[str, Baseline] = {}
    qa: AblationQa | None = None
    induce: list[AblationInduce] = []

    @field_validator("levels")
    @classmethod
    def _levels(cls, value):
        return DemoConfig._levels(value)


def load_ablation(path: Path) -> AblationConfig:
    """Load ablation paths without requiring future run artifacts to exist."""
    source = project_path(path, "ablation", True)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("ablation"), dict):
            raise ConfigError("ablation: expected a mapping")
        abl = AblationConfig.model_validate(raw["ablation"])
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"ablation: {exc}") from exc
    for run in abl.runs:
        run.config = project_path(run.config, "ablation.runs.config", True)
    for name, baseline in abl.baselines.items():
        baseline.eval_txt = project_path(baseline.eval_txt, f"ablation.baselines.{name}.eval_txt", True)
    if abl.qa is not None:
        abl.qa.config = project_path(abl.qa.config, "ablation.qa.config", True)
    boundary = (PROJECT_ROOT / "runs").resolve()
    for entry in abl.induce:
        for field in ("induce_dir", "pass2_run"):
            value = getattr(entry, field)
            if value is None:
                continue
            value = project_path(value, f"ablation.induce.{field}", False)
            if value == boundary or not value.is_relative_to(boundary):
                raise ConfigError(f"ablation.induce.{field}: must be below runs/")
            setattr(entry, field, value)
    return abl
