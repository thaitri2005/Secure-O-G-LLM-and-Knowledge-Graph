"""Markdown syntax that K1 table chunks add around the content (A-416).

A table chunk is Markdown: cell delimiters ``|``, a separator row ``| --- | --- |``, ``&#124;`` for a pipe inside a cell
and the placeholder ``<!-- image -->`` for a picture inside a cell. None of it is text of the source page. Two QA checks
need to look through it: the character ratio (extracted characters / PDF text characters) and the cross-representation
comparison of a table chunk with its grid. The patterns live in configs/qa (``markdown_syntax``), not here.

This module only counts or normalises; it never decides that a page or a table is right.
"""
from __future__ import annotations

import re
from typing import Any

UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def _non_space(text: str) -> int:
    return len("".join(text.split()))


def _compiled(rules: dict) -> tuple[re.Pattern | None, re.Pattern]:
    patterns = rules.get("placeholder_patterns") or []
    placeholder = re.compile("|".join(f"(?:{pattern})" for pattern in patterns), re.IGNORECASE) if patterns else None
    return placeholder, re.compile(rules.get("separator_cell_pattern", r":?-{3,}:?"))


def syntax_chars(text: str, rules: dict) -> int:
    """Non-space characters of ``text`` that are Markdown table syntax or placeholders (never counted: cell text).

    Counted: the unescaped ``|`` of a table line, every character of a separator row, placeholder matches and the surplus
    characters of an entity such as ``&#124;`` over the character it stands for. A pipe in running text is not counted
    because only lines that start with ``|`` are table lines."""
    placeholder, separator = _compiled(rules)
    total = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in UNESCAPED_PIPE.split(stripped[1:] if not stripped.endswith("|") else stripped[1:-1])]
            if cells and all(separator.fullmatch(cell) for cell in cells):
                total += _non_space(stripped)
                continue
            total += len(UNESCAPED_PIPE.findall(stripped))
        if placeholder is not None:
            total += sum(_non_space(match.group(0)) for match in placeholder.finditer(line))
        for entity, replacement in (rules.get("entities") or {}).items():
            total += line.count(entity) * (_non_space(entity) - _non_space(replacement))
    return total


def normalise_cell(text: str, rules: dict | None) -> str:
    """Cell text without Markdown placeholders, entities replaced, blanks collapsed. ``None`` rules: only blank collapse."""
    value = str(text if text is not None else "")
    if rules:
        for entity, replacement in (rules.get("entities") or {}).items():
            value = value.replace(entity, replacement)
        placeholder, _ = _compiled(rules)
        if placeholder is not None:
            value = placeholder.sub(" ", value)
    return " ".join(value.split())


def page_syntax_chars(texts: list[str], rules: dict[str, Any]) -> int:
    return sum(syntax_chars(text, rules) for text in texts)
