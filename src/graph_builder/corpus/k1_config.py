"""Load and validate the settings that turn finished corpus output into a K1 package."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

REPO = Path(__file__).resolve().parents[3]
DEFAULT_K1_CONFIG = REPO / "configs/corpus/k1.json"
KEYS = {"forms", "document_types", "report_context"}
FORM_KEYS = {"template", "minimum_label_share", "generic"}
REPORT_CONTEXT_KEYS = {"document_types", "date_patterns", "well_patterns"}


def load_k1_config(path: Path = DEFAULT_K1_CONFIG) -> dict[str, Any]:
    return validate_k1_config(json.loads(path.read_text(encoding="utf-8")))


def regex_list(name: str, patterns: Any, groups: int | None = None) -> list[str]:
    """Check a non-empty list of valid regular expressions, optionally with a fixed number of capture groups."""
    if not isinstance(patterns, list) or not patterns or any(not isinstance(pattern, str) or not pattern for pattern in patterns):
        raise ValueError(f"{name} must be a non-empty list of regular expressions")
    for pattern in patterns:
        try:
            compiled = re.compile(pattern)
        except re.error as error:
            raise ValueError(f"{name} contains an invalid regular expression {pattern!r}: {error}") from error
        if groups is not None and compiled.groups != groups:
            raise ValueError(f"{name} pattern {pattern!r} must have exactly {groups} capture group")
    return patterns


def validate_k1_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict) or set(config) != KEYS:
        raise ValueError(f"K1 configuration must contain exactly {sorted(KEYS)}")
    forms = config["forms"]
    if (not isinstance(forms, dict) or set(forms) != FORM_KEYS or not isinstance(forms["template"], str) or not forms["template"]
            or type(forms["minimum_label_share"]) not in (int, float) or not 0 < forms["minimum_label_share"] <= 1
            or type(forms["generic"]) is not bool):
        raise ValueError("forms needs template (path), minimum_label_share (0-1) and generic (true or false)")
    types = config["document_types"]
    if not isinstance(types, dict) or set(types) != {"rules", "default"} or not isinstance(types["default"], str) or not types["default"] \
            or not isinstance(types["rules"], list):
        raise ValueError("document_types needs rules (a list) and default (a string)")
    for rule in types["rules"]:
        if not isinstance(rule, dict) or set(rule) != {"pattern", "document_type"} or not isinstance(rule["document_type"], str) \
                or not rule["document_type"]:
            raise ValueError("every document_types rule needs exactly pattern and document_type")
        regex_list("document_types pattern", [rule["pattern"]])
    context = config["report_context"]
    if not isinstance(context, dict) or set(context) != REPORT_CONTEXT_KEYS:
        raise ValueError(f"report_context must contain exactly {sorted(REPORT_CONTEXT_KEYS)}")
    if not isinstance(context["document_types"], list) or any(not isinstance(name, str) or not name for name in context["document_types"]):
        raise ValueError("report_context document_types must be a list of document type names")
    regex_list("report_context date_patterns", context["date_patterns"], groups=1)
    regex_list("report_context well_patterns", context["well_patterns"], groups=1)
    return config


def template_path(config: dict[str, Any]) -> Path:
    """Resolve the form template path from the repository root."""
    return REPO / config["forms"]["template"]


def document_type(doc_id: str, config: dict[str, Any]) -> str:
    """Return the first rule whose pattern matches the document id, or the default type."""
    types = config["document_types"]
    return next((rule["document_type"] for rule in types["rules"] if re.search(rule["pattern"], doc_id)), types["default"])
