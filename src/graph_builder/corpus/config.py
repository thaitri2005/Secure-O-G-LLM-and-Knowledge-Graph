"""Load and validate corpus processing settings, and derive the processing fingerprint used as a cache key."""
from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
from pathlib import Path
from typing import Any

from .analysis import analysis_config
from .ocr_engines import ocr_config

KEYS = {"chunking", "filters", "table_mode", "ocr", "analysis", "quality", "segment_pages", "limits",
        "allowed_hosts", "document_timeout"}
FILTER_KEYS = {"margin_band", "frequency", "running_block_max_gap_lines", "running_block_alignment_lines",
               "running_line_fragment_gap_lines"}
QUALITY_KEYS = {"review_invalid_vietnamese_rate", "review_foreign_letter_rate", "min_ocr_page_chars"}
PIPELINE_VERSION = "corpus-1"


def load_config(path: Path) -> dict[str, Any]:
    return validate_config(json.loads(path.read_text(encoding="utf-8")))


def validate_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict) or set(config) != KEYS:
        raise ValueError(f"Corpus configuration must contain exactly {sorted(KEYS)}")
    chunking = config["chunking"]
    if (not isinstance(chunking, dict) or set(chunking) != {"max_chars", "strategy"}
            or type(chunking["max_chars"]) is not int or not 200 <= chunking["max_chars"] <= 20000
            or chunking["strategy"] not in ("paragraph", "page")):
        raise ValueError("chunking needs max_chars (200-20000) and strategy paragraph or page")
    filters = config["filters"]
    if not isinstance(filters, dict) or set(filters) != FILTER_KEYS or any(
            type(value) not in (int, float) or value < 0 for value in filters.values()):
        raise ValueError(f"filters must contain nonnegative {sorted(FILTER_KEYS)}")
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


def fingerprint(config: dict[str, Any], ocr_models: dict[str, str]) -> str:
    """Hash everything that changes derived output: settings, parser versions and OCR model bytes."""
    material = {"pipeline": PIPELINE_VERSION, "docling": version("docling"), "docling-core": version("docling-core"),
                "settings": {key: config[key] for key in sorted(KEYS - {"allowed_hosts", "limits"})},
                "ocr_models": ocr_models}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:16]
