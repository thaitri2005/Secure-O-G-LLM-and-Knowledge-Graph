"""Load and validate the settings that turn finished corpus output into a K1 package."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

REPO = Path(__file__).resolve().parents[3]
DEFAULT_K1_CONFIG = REPO / "configs/corpus/k1.json"
KEYS = {"forms", "document_types", "report_context"}
OPTIONAL_KEYS = {"table_rules"}  # absent means no table rule is applied
TABLE_RULES = {"operations_summary"}
OPERATIONS_RULE_KEYS = {"document_types", "schema", "recognition", "tolerances"}
SCHEMA_KEYS = {"title_words", "columns", "patterns", "mark", "annotation_kinds"}
RECOGNITION_KEYS = {"phrase_gap_em_title", "annotation_min_gap_em_title", "annotation_max_tokens", "title_header_gap_em_header"}
TOLERANCE_KEYS = {"line_gap_em_header", "continuation_indent_em_header", "band_margin_em_header", "code_zone_extension",
                  "elapsed_tolerance_minutes", "docling_overlap", "section_title"}
COLUMN_KINDS = ("time", "time", "hours", "depth", "code", "text", "mark")  # the fixed row grammar of the rule
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
    if not isinstance(config, dict) or set(config) - OPTIONAL_KEYS != KEYS:
        raise ValueError(f"K1 configuration must contain exactly {sorted(KEYS)} (and optionally {sorted(OPTIONAL_KEYS)})")
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
    rules = config.get("table_rules", {})
    if not isinstance(rules, dict) or set(rules) - TABLE_RULES:
        raise ValueError(f"table_rules may only contain {sorted(TABLE_RULES)}")
    for name, rule in rules.items():
        names = rule.get("document_types") if isinstance(rule, dict) else None
        if not isinstance(rule, dict) or set(rule) != OPERATIONS_RULE_KEYS or not isinstance(names, list) or not names \
                or any(not isinstance(item, str) or not item for item in names):
            raise ValueError(f"table_rules {name} needs exactly {sorted(OPERATIONS_RULE_KEYS)} "
                             "(document_types is a non-empty list of document type names)")
        validate_operations_summary(rule)
    return config


def exact_keys(name: str, value: Any, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"table_rules operations_summary {name} must contain exactly {sorted(keys)}")
    return value


def number(name: str, value: Any, low: float, high: float, low_open: bool = True, high_open: bool = False) -> None:
    """A real number (not a bool) inside the interval; the ends are open or closed as given."""
    if type(value) not in (int, float) or not (low < value if low_open else low <= value) \
            or not (value < high if high_open else value <= high):
        raise ValueError(f"table_rules operations_summary {name} must be a number between {low} and {high}")


def integer(name: str, value: Any, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"table_rules operations_summary {name} must be an integer from {low} to {high}")


def normalised_label(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.lower())


def validate_operations_summary(rule: dict[str, Any]) -> None:
    """Check the schema, recognition thresholds and tolerances of the Operations Summary rule (see ``ops_tables``).

    There are no defaults in the code: every key is required and checked here, so a typo cannot silently change the
    recognised format. The row grammar (the kinds of the seven columns) is fixed; labels, patterns and tolerances are
    configurable.
    """
    schema = exact_keys("schema", rule["schema"], SCHEMA_KEYS)
    words = schema["title_words"]
    if not isinstance(words, list) or len(words) != 2 or any(not isinstance(word, str) or not word or re.search(r"\s", word)
                                                              for word in words):
        raise ValueError("table_rules operations_summary title_words must be two non-empty words without whitespace")
    columns = schema["columns"]
    if not isinstance(columns, list) or [column.get("kind") if isinstance(column, dict) else None for column in columns] \
            != list(COLUMN_KINDS):
        raise ValueError(f"table_rules operations_summary columns must have the kinds {list(COLUMN_KINDS)} in this order")
    labels = []
    for column in columns:
        exact_keys("columns[]", column, {"label", "kind"})
        if not isinstance(column["label"], str) or not normalised_label(column["label"]):
            raise ValueError("table_rules operations_summary column labels must be non-empty text with letters or digits")
        labels.append(normalised_label(column["label"]))
    if len(set(labels)) != len(labels):
        raise ValueError("table_rules operations_summary column labels must differ after normalisation")
    patterns = exact_keys("patterns", schema["patterns"], {"time", "hours", "depth", "code"})
    regex_list("operations_summary patterns", list(patterns.values()))
    time = re.compile(patterns["time"])
    if not all(time.search(value) for value in ("0:00", "9:05", "24:00")) or time.search("abc"):
        raise ValueError("table_rules operations_summary patterns.time must match 0:00, 9:05 and 24:00 but not abc")
    mark = exact_keys("mark", schema["mark"], {"glyph", "lookalikes"})
    if not isinstance(mark["glyph"], str) or len(mark["glyph"]) != 1 or not isinstance(mark["lookalikes"], str):
        raise ValueError("table_rules operations_summary mark needs a one-character glyph and a string of lookalikes")
    kinds = schema["annotation_kinds"]
    if not isinstance(kinds, list):
        raise ValueError("table_rules operations_summary annotation_kinds must be a list")
    names = []
    for kind in kinds:
        exact_keys("annotation_kinds[]", kind, {"kind", "pattern", "sample"})
        if not isinstance(kind["kind"], str) or not kind["kind"] or not isinstance(kind["sample"], str) or not kind["sample"]:
            raise ValueError("table_rules operations_summary annotation_kinds need a kind name and a non-empty sample")
        names.append(kind["kind"])
        regex_list("operations_summary annotation_kinds pattern", [kind["pattern"]], groups=1)
        found = re.search(kind["pattern"], kind["sample"], re.IGNORECASE)
        if not found or not re.fullmatch(r"\d+", found.group(1) or ""):
            raise ValueError(f"annotation_kinds pattern {kind['pattern']!r} must match its sample with digits in group 1")
    if len(set(names)) != len(names):
        raise ValueError("table_rules operations_summary annotation_kinds names must differ")
    recognition = exact_keys("recognition", rule["recognition"], RECOGNITION_KEYS)
    for key in RECOGNITION_KEYS - {"annotation_max_tokens"}:
        number(key, recognition[key], 0, 10)
    integer("annotation_max_tokens", recognition["annotation_max_tokens"], 1, 50)
    if recognition["phrase_gap_em_title"] >= recognition["annotation_min_gap_em_title"]:
        raise ValueError("table_rules operations_summary phrase_gap_em_title must be smaller than annotation_min_gap_em_title")
    tolerances = exact_keys("tolerances", rule["tolerances"], TOLERANCE_KEYS)
    for key in ("line_gap_em_header", "continuation_indent_em_header", "band_margin_em_header"):
        number(key, tolerances[key], 0, 10)
    number("code_zone_extension", tolerances["code_zone_extension"], 0, 2, low_open=False)
    number("elapsed_tolerance_minutes", tolerances["elapsed_tolerance_minutes"], 0, 10)
    number("docling_overlap", tolerances["docling_overlap"], 0, 1)
    section = exact_keys("section_title", tolerances["section_title"], {"centre_tolerance_page_width", "max_words", "word_pattern"})
    number("centre_tolerance_page_width", section["centre_tolerance_page_width"], 0, 0.5, high_open=True)
    integer("max_words", section["max_words"], 1, 10)
    regex_list("operations_summary section_title word_pattern", [section["word_pattern"]])


def template_path(config: dict[str, Any]) -> Path:
    """Resolve the form template path from the repository root."""
    return REPO / config["forms"]["template"]


def document_type(doc_id: str, config: dict[str, Any]) -> str:
    """Return the first rule whose pattern matches the document id, or the default type."""
    types = config["document_types"]
    return next((rule["document_type"] for rule in types["rules"] if re.search(rule["pattern"], doc_id)), types["default"])
