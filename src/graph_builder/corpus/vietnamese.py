"""Check Vietnamese syllable spelling so that OCR and text-layer errors can be detected without reference text."""
from __future__ import annotations

from functools import lru_cache
import re
import unicodedata

TONES = {"̀", "́", "̃", "̉", "̣"}
CHECKED_TONES = {"́", "̣"}  # the only tones allowed on syllables ending in -c, -ch, -p, -t
LETTERS = set("aăâbcdđeêghiklmnoôơpqrstuưvxy")
VIETNAMESE_ONLY = set("ăâđêôơư")
ONSETS = sorted(["", "b", "c", "ch", "d", "đ", "g", "gh", "gi", "h", "k", "kh", "l", "m", "n", "ng", "ngh",
                 "nh", "p", "ph", "qu", "r", "s", "t", "th", "tr", "v", "x"], key=len, reverse=True)
RHYMES = set("""
a ac ach ai am an ang anh ao ap at au ay
ăc ăm ăn ăng ăp ăt
âc âm ân âng âp ât âu ây
e ec em en eng eo ep et
ê êch êm ên ênh êp êt êu
i ia ich im in inh ip it iu iêc iêm iên iêng iêp iêt iêu
o oa oac oach oai oam oan oang oanh oao oap oat oay oăc oăm oăn oăng oăt oc oe oen oeo oet oi om on ong
ooc oong op ot
ô ôc ôi ôm ôn ông ôp ôt
ơ ơi ơm ơn ơp ơt
u ua uân uâng uât uây uc ui um un ung uơ up ut uy uya uych uyên uyêt uyn uynh uyp uyt uyu uê uêch uênh
uôc uôi uôm uôn uông uôt
ư ưa ưc ưi ưm ưn ưng ươ ươc ươi ươm ươn ương ươp ươt ươu ưt ưu
y yêm yên yêng yêt yêu
""".split())
TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


def split_tone(word: str) -> tuple[str, list[str]]:
    """Return the lowercase syllable without tone marks, and the tone marks found."""
    decomposed = unicodedata.normalize("NFD", word.lower())
    tones = [char for char in decomposed if char in TONES]
    base = unicodedata.normalize("NFC", "".join(char for char in decomposed if char not in TONES))
    return base, tones


@lru_cache(maxsize=65536)
def is_valid_syllable(word: str) -> bool:
    """True if the word is a well-formed Vietnamese syllable (onset + rhyme + at most one legal tone)."""
    base, tones = split_tone(word)
    if len(tones) > 1 or not base or set(base) - LETTERS:
        return False
    for onset in ONSETS:
        if not base.startswith(onset):
            continue
        rhyme = base[len(onset):]
        if onset == "qu" and rhyme.startswith("u"):
            continue
        if onset == "gi" and rhyme == "":
            rhyme = "i"
        if rhyme not in RHYMES:
            continue
        if tones and rhyme.endswith(("c", "ch", "p", "t")) and tones[0] not in CHECKED_TONES:
            continue
        return True
    return False


def is_vietnamese_marked(word: str) -> bool:
    """True if the word carries a mark that only Vietnamese spelling uses here (tone, horn, breve, circumflex, đ)."""
    decomposed = unicodedata.normalize("NFD", word.lower())
    return any(char in TONES for char in decomposed) or bool(set(unicodedata.normalize("NFC", decomposed)) & VIETNAMESE_ONLY)


def is_foreign_letter_word(word: str) -> bool:
    """True if the word contains letters outside basic Latin and Vietnamese, a sign of a broken text layer or legacy font."""
    base = unicodedata.normalize("NFC", "".join(char for char in unicodedata.normalize("NFD", word.lower()) if char not in TONES))
    return any(not ("a" <= char <= "z") and char not in VIETNAMESE_ONLY for char in base)


def text_profile(text: str) -> dict[str, float | int]:
    """Count words and spelling problems in a page or chunk of text.

    `invalid_vietnamese` counts words with Vietnamese marks that are not well-formed syllables;
    `foreign_letters` counts words with letters that neither Vietnamese nor basic Latin uses.
    """
    # Single letters are list markers ("a)", "đ)") or initials, not syllables.
    words = [word for word in TOKEN.findall(text) if len(word) > 1]
    marked = [word for word in words if is_vietnamese_marked(word)]
    invalid = [word for word in marked if not is_valid_syllable(word)]
    foreign = [word for word in words if is_foreign_letter_word(word) and not is_vietnamese_marked(word)]
    return {"words": len(words), "vietnamese_words": len(marked), "invalid_vietnamese": len(invalid),
            "foreign_letters": len(foreign),
            "invalid_vietnamese_rate": round(len(invalid) / len(marked), 4) if marked else 0.0,
            "foreign_letter_rate": round(len(foreign) / len(words), 4) if words else 0.0}
