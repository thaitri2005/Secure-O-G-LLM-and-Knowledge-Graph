"""Load and validate corpus processing settings, and derive the processing fingerprint used as a cache key."""
from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
from typing import Any

from ..ingestion.tables import TABLE_MARKDOWN_MODES
from .analysis import analysis_config
from .label_value import label_value_settings
from .ocr_engines import ocr_config
from .quarantine import quarantine_settings

KEYS = {"chunking", "filters", "table_mode", "ocr", "analysis", "quality", "segment_pages", "limits",
        "allowed_hosts", "document_timeout"}
FILTER_KEYS = {"margin_band", "frequency", "running_block_max_gap_lines", "running_block_alignment_lines",
               "running_line_fragment_gap_lines"}
OPTIONAL_FILTER_KEYS = {"keep_line_patterns", "running_line_position_tolerance", "running_line_min_pages",
                        "running_line_keep_varying_numbers", "toc_leader_min_dots"}
QUALITY_KEYS = {"review_invalid_vietnamese_rate", "review_foreign_letter_rate", "min_ocr_page_chars"}
PIPELINE_VERSION = "corpus-1"
OPTIONAL_KEYS = {"cache"}  # C-04: absent unless supplied, so existing fingerprints and caches do not change
CACHE_KEYS = {"code_version"}
# Source files whose bytes enter the fingerprint when cache.code_version is on. Everything that can change the
# work/ outputs is included; the stages that only read them (QA, K1 and release export, the command line) are not.
CODE_PACKAGES = ("corpus", "ingestion")
CODE_EXCLUDED = ("corpus/qa/", "corpus/k1_", "corpus/export.py", "corpus/__main__.py")


def load_config(path: Path) -> dict[str, Any]:
    return validate_config(json.loads(path.read_text(encoding="utf-8")))


def keep_pattern(patterns: Any) -> re.Pattern[str] | None:
    """Compile ``keep_line_patterns`` into one case-insensitive regex; None when no patterns are given."""
    if not isinstance(patterns, list) or any(not isinstance(pattern, str) or not pattern for pattern in patterns):
        raise ValueError("keep_line_patterns must be a list of non-empty regular expressions")
    try:
        return re.compile("|".join(f"(?:{pattern})" for pattern in patterns), re.IGNORECASE) if patterns else None
    except re.error as error:
        raise ValueError(f"keep_line_patterns contains an invalid regular expression: {error}") from error


def validate_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict) or not KEYS <= set(config) <= KEYS | OPTIONAL_KEYS:
        raise ValueError(f"Corpus configuration must contain exactly {sorted(KEYS)} and optionally {sorted(OPTIONAL_KEYS)}")
    if "cache" in config and (not isinstance(config["cache"], dict) or set(config["cache"]) != CACHE_KEYS
                              or type(config["cache"]["code_version"]) is not bool):
        raise ValueError("cache must be an object with exactly one boolean key, code_version")
    chunking = config["chunking"]
    if (not isinstance(chunking, dict) or not {"max_chars", "strategy"} <= set(chunking) <= {
            "max_chars", "strategy", "table_markdown", "label_value", "quarantine", "preserve_list_markers"}
            or type(chunking["max_chars"]) is not int or not 200 <= chunking["max_chars"] <= 20000
            or chunking["strategy"] not in ("paragraph", "page")
            or chunking.get("table_markdown", "docling") not in TABLE_MARKDOWN_MODES):
        raise ValueError("chunking needs max_chars (200-20000) and strategy paragraph or page, "
                         f"and optionally table_markdown {list(TABLE_MARKDOWN_MODES)}, label_value, quarantine "
                         "and preserve_list_markers")
    if type(chunking.get("preserve_list_markers", False)) is not bool:
        raise ValueError("chunking.preserve_list_markers must be a boolean")
    if "label_value" in chunking:
        label_value_settings(chunking["label_value"])
    if "quarantine" in chunking:
        quarantine_settings(chunking["quarantine"])
    filters = config["filters"]
    if not isinstance(filters, dict) or not FILTER_KEYS <= set(filters) <= FILTER_KEYS | OPTIONAL_FILTER_KEYS or any(
            type(filters[key]) not in (int, float) or filters[key] < 0 for key in FILTER_KEYS):
        raise ValueError(f"filters must contain nonnegative {sorted(FILTER_KEYS)} and optionally {sorted(OPTIONAL_FILTER_KEYS)}")
    if "keep_line_patterns" in filters:
        keep_pattern(filters["keep_line_patterns"])
    if type(filters.get("running_line_keep_varying_numbers", False)) is not bool:
        raise ValueError("running_line_keep_varying_numbers must be a boolean")
    if "running_line_position_tolerance" in filters and (type(filters["running_line_position_tolerance"]) not in (int, float)
                                                         or not 0 < filters["running_line_position_tolerance"] <= 0.5):
        raise ValueError("running_line_position_tolerance must be a fraction of the page height, above 0 and at most 0.5 "
                         "(positional repetition applies to table cells only; text items keep legacy decisions)")
    if "running_line_min_pages" in filters and (type(filters["running_line_min_pages"]) is not int
                                                or not 2 <= filters["running_line_min_pages"] <= 1000):
        raise ValueError("running_line_min_pages must be an integer number of distinct pages, 2 to 1000")
    if "toc_leader_min_dots" in filters and (type(filters["toc_leader_min_dots"]) is not int
                                             or not 4 <= filters["toc_leader_min_dots"] <= 100):
        raise ValueError("toc_leader_min_dots must be an integer number of dots, 4 to 100 "
                         "(a shorter run counts as a table-of-contents leader only when a page number follows it)")
    if config["table_mode"] not in ("fast", "accurate"):
        raise ValueError("table_mode must be fast or accurate")
    config["ocr"] = ocr_config(config["ocr"])
    config["analysis"] = analysis_config(config["analysis"])
    quality = config["quality"]
    if not isinstance(quality, dict) or set(quality) != QUALITY_KEYS or any(
            type(value) not in (int, float) or value < 0 for value in quality.values()):
        raise ValueError(f"quality must contain nonnegative {sorted(QUALITY_KEYS)}")
    if type(config["segment_pages"]) is not int or not 1 <= config["segment_pages"] <= 500:
        raise ValueError("segment_pages must be between 1 and 500")
    limits = config["limits"]
    if (not isinstance(limits, dict) or set(limits) != {"max_bytes", "max_pages"}
            or any(type(value) is not int or value < 1 for value in limits.values())):
        raise ValueError("limits must contain positive integer max_bytes and max_pages")
    hosts = config["allowed_hosts"]
    if not isinstance(hosts, list) or any(not isinstance(host, str) or "/" in host or not host for host in hosts):
        raise ValueError("allowed_hosts must be a list of host names")
    timeout = config["document_timeout"]
    if timeout is not None and (type(timeout) not in (int, float) or timeout <= 0):
        raise ValueError("document_timeout must be positive seconds or null")
    return config


def code_digest(root: Path | None = None) -> str:
    """SHA256 over the processing source files (relative path + content with LF line endings), in sorted order."""
    root = root or Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for package in CODE_PACKAGES:
        for path in sorted((root / package).rglob("*.py")):
            name = path.relative_to(root).as_posix()
            if name.startswith(CODE_EXCLUDED):
                continue
            digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).digest())
    return digest.hexdigest()


def fingerprint(config: dict[str, Any], ocr_models: dict[str, str]) -> str:
    """Hash everything that changes derived output: settings, parser versions and OCR model bytes.

    With the optional ``cache.code_version`` switched on, the processing source files are hashed in as well, so a code
    change can no longer reuse an older result. The optional running-line position tolerance also carries a semantics
    marker: its table-cell-only decisions must not reuse older global-tolerance work. With both options absent,
    the fingerprint is unchanged.
    """
    material = {"pipeline": PIPELINE_VERSION, "docling": version("docling"), "docling-core": version("docling-core"),
                "settings": {key: config[key] for key in sorted(KEYS - {"allowed_hosts", "limits"})},
                "ocr_models": ocr_models}
    if "running_line_position_tolerance" in config["filters"]:
        material["running_line_semantics"] = 2
    if config["analysis"].get("page_orientation", {}).get("mode") == "verify":
        material["orientation_verification_semantics"] = 3
    if config.get("cache", {}).get("code_version"):
        material["code"] = code_digest()
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:16]
