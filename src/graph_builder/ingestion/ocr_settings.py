"""Validated multilingual OCR settings, independent of the model runtime."""
import re


DEFAULT_OCR = {"languages": ["vi", "en"], "mode": "auto", "confidence_threshold": 0.5}


def ocr_settings(options: dict) -> dict:
    supplied = options.get("ocr", {})
    if not isinstance(supplied, dict) or set(supplied) - DEFAULT_OCR.keys():
        raise ValueError("ocr accepts languages, mode and confidence_threshold only")
    settings = {**DEFAULT_OCR, **supplied}
    languages = settings["languages"]
    if (not isinstance(languages, list) or not languages
            or any(not isinstance(x, str) or not re.fullmatch(r"[a-z]{2,3}(?:_[a-z]+)?", x) for x in languages)
            or len(set(languages)) != len(languages)):
        raise ValueError("ocr.languages must be a nonempty list of unique EasyOCR language codes")
    if not isinstance(settings["mode"], str) or settings["mode"] not in {"auto", "full_page"}:
        raise ValueError("ocr.mode must be auto or full_page")
    threshold = settings["confidence_threshold"]
    if type(threshold) not in (int, float) or not 0 <= threshold <= 1:
        raise ValueError("ocr.confidence_threshold must be between 0 and 1")
    return settings
