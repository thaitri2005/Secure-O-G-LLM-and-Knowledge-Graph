"""Deterministic identifiers, text spans, temporal parsing, and UTF-8 JSON I/O."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

TIME_ISO = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])|\n+")
GROUND_STOPWORDS = frozenset("a an the of in on at to is was are were be by for and".split())
_MONTHS = {name.lower(): i for i, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), 1)}
_MONTH = "(?:" + "|".join(_MONTHS) + ")"


def h(*parts) -> str:
    """Hash separator-delimited values, representing None as an empty field."""
    return hashlib.sha1("\x1f".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


def surface_key(s: str) -> str:
    """Normalize compatibility characters, case, and whitespace."""
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def match_key(s: str) -> str:
    """Matching-only key for EDC/WebNLG surfaces; never used for ids, names or exports."""
    t = s.replace("_", " ").strip()
    if len(t) >= 2 and t[0] == t[-1] == '"':
        t = t[1:-1]
    return surface_key(t)


def tokens(s: str) -> list[str]:
    return re.findall(r"[0-9a-z]+", surface_key(s))


def predicate_words(p: str) -> str:
    """Split camelCase and underscores into normalized predicate words."""
    return " ".join(re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", p).replace("_", " ").lower().split())


def predicate_key(p: str) -> str:
    return norm_pred(predicate_words(p))


def predicate_redundancy(predicates) -> float:
    distinct = set(predicates)
    return round(1 - len({predicate_key(p) for p in distinct}) / len(distinct), 4) if distinct else 0.0


def norm_pred(p: str) -> str:
    return re.sub(r"^(?:has been|had been|was|were|is|are|has|have|had)\s+", "", surface_key(p))


def pad(t: str) -> str:
    return t + "-01-01" if len(t) == 4 else t + "-01" if len(t) == 7 else t


def holds_at(vf, vt, at) -> bool:
    return (vf is None or pad(vf) <= pad(at)) and (vt is None or pad(at) < pad(vt))


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def split_sentences(text: str, base: int = 0) -> list[tuple[int, int]]:
    """Return nonempty, trimmed sentence offsets relative to a document."""
    spans, start = [], 0
    for match in SENT_SPLIT.finditer(text):
        left, right = _trim(text, start, match.start())
        if left < right:
            spans.append((base + left, base + right))
        start = match.end()
    left, right = _trim(text, start, len(text))
    if left < right:
        spans.append((base + left, base + right))
    return spans


def chunk_spans(text: str, max_chars: int) -> list[tuple[int, int]]:
    """Pack whole sentences and split oversized sentences at whitespace."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    pieces = []
    for start, end in split_sentences(text):
        while end - start > max_chars:
            limit = start + max_chars
            cut = next((i for i in range(limit, start, -1) if text[i].isspace()), limit)
            left, right = _trim(text, start, cut)
            if left < right:
                pieces.append((left, right))
            start, _ = _trim(text, cut, end)
        if start < end:
            pieces.append((start, end))
    packed = []
    for start, end in pieces:
        if packed and end - packed[-1][0] <= max_chars:
            packed[-1] = (packed[-1][0], end)
        else:
            packed.append((start, end))
    return packed


ABBREVIATIONS = frozenset("mr mrs ms dr prof sr jr st mt ft gen col lt capt sgt rev hon gov sen rep pres no nos vol vols ed eds "
                          "co corp inc ltd bros dept univ est approx ca cf vs etc al fig figs translit lit transl orig op "
                          "jan feb mar apr jun jul aug sep sept oct nov dec".split())
PRONOUNS = frozenset("he she it they his her its their him them".split())


def split_sentences_abbrev(text: str, base: int = 0) -> list[tuple[int, int]]:
    """Keep abbreviation periods inside grounding sentences, preserving offsets."""
    spans, start = [], 0
    for match in SENT_SPLIT.finditer(text):
        prefix = text[:match.start()]
        word = re.search(r"([A-Za-z]+)\.$", prefix)
        if "\n" not in match[0] and word and (len(word[1]) == 1 or word[1].lower() in ABBREVIATIONS
                                               or re.search(r"(?:[A-Za-z]\.){2,}$", prefix)):
            continue
        left, right = _trim(text, start, match.start())
        if left < right:
            spans.append((base + left, base + right))
        start = match.end()
    left, right = _trim(text, start, len(text))
    if left < right:
        spans.append((base + left, base + right))
    return spans


def sentence_form(sentence: str) -> str:
    return _base_form(sentence) + " " + " ".join(find_dates(sentence))


def contains_form(form_of_sentence: str, form: str) -> bool:
    return re.search((r"(?<!\d)" if form[:1].isdigit() else "") + re.escape(form)
                     + (r"(?!\d)" if form[-1:].isdigit() else ""), form_of_sentence) is not None


def _date_matches(text: str) -> list[tuple[int, int, str]]:
    """Find nonoverlapping dates in text order, preferring specific patterns."""
    patterns = [
        (r"\b\d{4}-\d{2}-\d{2}\b", lambda m: m[0]),
        (r"\b\d{4}-\d{2}\b", lambda m: m[0]),
        (rf"\b({_MONTH})\s+(\d{{1,2}}),?\s+(\d{{4}})\b",
         lambda m: f"{m[3]}-{_MONTHS[m[1].lower()]:02d}-{int(m[2]):02d}"),
        (rf"\b(\d{{1,2}})\s+({_MONTH})\s+(\d{{4}})\b",
         lambda m: f"{m[3]}-{_MONTHS[m[2].lower()]:02d}-{int(m[1]):02d}"),
        (rf"\b({_MONTH})\s+(\d{{4}})\b",
         lambda m: f"{m[2]}-{_MONTHS[m[1].lower()]:02d}"),
        (r"\b(1[5-9]\d{2}|20\d{2})\b", lambda m: m[0]),
    ]
    matches = []
    for pattern, convert in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if not any(match.start() < end and start < match.end() for start, end, _ in matches):
                matches.append((match.start(), match.end(), convert(match)))
    matches.sort()
    return matches


def find_dates(text: str) -> list[str]:
    return [iso for _, _, iso in _date_matches(text)]


def extract_time(text: str, obj: str | None) -> str | None:
    """Find the highest-specificity nonoverlapping dates nearest the object."""
    matches = _date_matches(text)
    if not matches:
        return None
    location = re.search(re.escape(obj), text, re.IGNORECASE) if obj else None
    if location is None:
        return matches[0][2]
    center = (location.start() + location.end()) / 2
    return min(matches, key=lambda item: (abs((item[0] + item[1]) / 2 - center), item[0]))[2]


DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
_INITIALS = re.compile(r"\b([a-z])\.\s+(?=[a-z]\.)")
_NUM_IN_TEXT = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d,])|(?<![\d.])\d+\.0+(?!\d)")
NUMBER_UNIT = re.compile(r"([+-]?\d[\d,]*(?:\.\d+)?)\s*(?:\(?[a-z%]+\)?)?")


def _canon_number(t: str) -> str:
    t = t.replace(",", "")
    return t.split(".")[0] if re.fullmatch(r"\d+\.0+", t) else t


def _base_form(s: str) -> str:
    """Shared matching-only normalization; never changes exported surfaces."""
    t = "".join(c for c in unicodedata.normalize("NFKD", match_key(s)) if not unicodedata.combining(c))
    t = t.translate(str.maketrans({c: "-" for c in DASHES})).replace("&", " and ")
    t = _INITIALS.sub(r"\1.", " ".join(t.split()))
    return _NUM_IN_TEXT.sub(lambda m: _canon_number(m[0]), t)


def norm_surface(s: str) -> str:
    t = _base_form(s)
    m = NUMBER_UNIT.fullmatch(t)
    return _canon_number(m[1]) if m else t


def literal_forms(s: str) -> frozenset[str]:
    t = norm_surface(s)
    dates = _date_matches(t)
    forms = {t}
    if len(dates) == 1 and dates[0][:2] == (0, len(t)):
        forms.add(dates[0][2])
    return frozenset(forms)


def number_tokens(s: str) -> frozenset[str]:
    """Numbers and ordinals, with conservative uppercase Roman recognition."""
    cardinal = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
    ordinal = "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth".split()
    words = {word: str(i) for seq in (cardinal, ordinal) for i, word in enumerate(seq, 1)}
    found = set()
    for token in re.findall(r"\b\w+\b", s.replace("_", " ")):
        digit = re.fullmatch(r"(\d+)(?:st|nd|rd|th)?", token, re.IGNORECASE)
        if digit:
            found.add(digit[1])
        elif token.casefold() in words:
            found.add(words[token.casefold()])
        elif re.fullmatch(r"[IVX]{2,}", token) and re.fullmatch(r"X{0,3}(?:IX|IV|V?I{0,3})", token):
            values = [dict(I=1, V=5, X=10)[c] for c in token]
            found.add(str(sum(-v if i + 1 < len(values) and v < values[i + 1] else v for i, v in enumerate(values))))
    return frozenset(found)


def parse_yes_no(content: str, extended: bool = False) -> str | None:
    if not isinstance(content, str):
        return None
    choices = "not supported|unsupported|supported|yes|no|true|false" if extended else "yes|no|true|false"
    match = re.search(r"\b(" + choices + r")\b", content, re.IGNORECASE)
    if not match:
        return None
    return "yes" if match[0].lower() in {"yes", "true", "supported"} else "no"


def cj(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(p: Path) -> str:
    digest = hashlib.sha256()
    with Path(p).open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=1) + "\n")


def write_jsonl(path: Path, rows) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(cj(row) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def iter_jsonl(path: Path):
    """Yield UTF-8 JSONL records without materializing the input file."""
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)
