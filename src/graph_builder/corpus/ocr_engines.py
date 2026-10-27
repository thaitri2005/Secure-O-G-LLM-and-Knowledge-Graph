"""Validated OCR engine settings, pinned model files and offline model resolution for Docling conversion.

Engines:
- ``vietocr`` (default): PP-OCRv6 line detection + VietOCR recognition; reads Vietnamese tone marks and English.
- ``rapidocr``: PP-OCRv6 detection and recognition; fast, good for English, drops most Vietnamese letters.
- ``easyocr``: EasyOCR Latin model; kept for comparison with earlier runs.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import shutil
import tempfile
from typing import Any
from urllib.request import urlopen

ENGINES = ("vietocr", "rapidocr", "easyocr")
DEFAULT_OCR = {"engine": "vietocr", "languages": ["vi", "en"], "model_size": "small",
               "scale": 2.5, "confidence_threshold": 0.5}
RAPIDOCR_FOLDER = "RapidOcr"
VIETOCR_FOLDER = "vietocr"
# Published VietOCR files, pinned by digest (Apache-2.0, https://github.com/pbcquoc/vietocr).
VIETOCR_FILES = {
    "vgg_transformer.pth": ("https://vocr.vn/data/vietocr/vgg_transformer.pth",
                            "380512193a8b6cbf6fad80deacdc9b6939d10d473d199892fc6408d13775ea59"),
    "base.yml": ("https://raw.githubusercontent.com/pbcquoc/vietocr/master/config/base.yml",
                 "9c8283fadb950f06f5d3400475f80d5355700ff315c9c48b7875e6ea66647d1c"),
    "vgg-transformer.yml": ("https://raw.githubusercontent.com/pbcquoc/vietocr/master/config/vgg-transformer.yml",
                            "0df9feee197754c7381871e5dfd07c6f3e292a4853eece6f1af240923e57c907"),
}


def ocr_config(supplied: dict[str, Any] | None) -> dict[str, Any]:
    """Return complete OCR settings, rejecting unknown keys and invalid values."""
    supplied = supplied or {}
    if not isinstance(supplied, dict) or set(supplied) - DEFAULT_OCR.keys():
        raise ValueError(f"ocr accepts only {sorted(DEFAULT_OCR)}")
    settings = {**DEFAULT_OCR, **supplied}
    if settings["engine"] not in ENGINES:
        raise ValueError(f"ocr.engine must be one of {ENGINES}")
    languages = settings["languages"]
    if (not isinstance(languages, list) or not languages or len(set(languages)) != len(languages)
            or any(not isinstance(code, str) or not code.isalpha() or not 2 <= len(code) <= 3 for code in languages)):
        raise ValueError("ocr.languages must be a nonempty list of unique ISO language codes")
    if settings["model_size"] not in ("small", "medium"):
        raise ValueError("ocr.model_size must be small or medium")
    if type(settings["scale"]) not in (int, float) or not 1 <= settings["scale"] <= 6:
        raise ValueError("ocr.scale must be between 1 and 6")
    if type(settings["confidence_threshold"]) not in (int, float) or not 0 <= settings["confidence_threshold"] <= 1:
        raise ValueError("ocr.confidence_threshold must be between 0 and 1")
    return settings


def model_files(models: Path, settings: dict[str, Any]) -> list[Path]:
    """List the local model files an engine needs; conversion never downloads them."""
    rapid = models / RAPIDOCR_FOLDER
    size = settings["model_size"]
    if settings["engine"] == "vietocr":
        return [rapid / f"PP-OCRv6_det_{size}.onnx", rapid / "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                rapid / "PP-OCRv6_rec_small.onnx", *(models / VIETOCR_FOLDER / name for name in VIETOCR_FILES)]
    if settings["engine"] == "rapidocr":
        return [rapid / f"PP-OCRv6_det_{size}.onnx", rapid / f"PP-OCRv6_rec_{size}.onnx",
                rapid / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"]
    return sorted(models.glob("*.pth"))


def engine_fingerprint(models: Path, settings: dict[str, Any]) -> dict[str, Any]:
    """Identify the engine version, settings and exact model bytes for cache keys and manifests."""
    from .store import file_sha256
    packages = {"vietocr": ("vietocr", "rapidocr", "onnxruntime", "torch"),
                "rapidocr": ("rapidocr", "onnxruntime"), "easyocr": ("easyocr", "torch")}[settings["engine"]]
    try:
        runtime = {package: version(package) for package in packages}
    except PackageNotFoundError as error:
        raise ValueError(f"OCR engine {settings['engine']} is not installed: {error}") from error
    files = model_files(models, settings)
    missing = [str(path) for path in files if not path.is_file()]
    if missing or not files:
        raise ValueError("OCR model files are missing; run `python -m graph_builder.corpus models`. "
                         f"Missing: {missing or models}")
    digests = {path.name: file_sha256(path) for path in files}
    if settings["engine"] == "vietocr":
        for name, (_, expected) in VIETOCR_FILES.items():
            if digests[name] != expected:
                raise ValueError(f"VietOCR file {name} does not match its pinned SHA256")
    return {"settings": settings, "runtime": runtime, "models": digests}


def ocr_options(models: Path, settings: dict[str, Any], full_page: bool):
    """Build Docling OCR options that load pinned local models only."""
    from docling.datamodel.pipeline_options import EasyOcrOptions, OcrMode, RapidOcrOptions
    mode = OcrMode.FULL_PAGE if full_page else OcrMode.DEFAULT
    files = model_files(models, settings)
    if settings["engine"] == "vietocr":
        from .vietocr_engine import VietOcrOptions, register
        register()
        return VietOcrOptions(mode=mode, lang=settings["languages"], scale=settings["scale"],
                              det_model_path=str(files[0]), weights_path=str(models / VIETOCR_FOLDER / "vgg_transformer.pth"),
                              config_dir=str(models / VIETOCR_FOLDER))
    if settings["engine"] == "rapidocr":
        det, rec, cls = files
        # PP-OCR recognizers are multilingual per model; Docling accepts one language tag.
        return RapidOcrOptions(mode=mode, lang=[settings["languages"][0]], scale=settings["scale"],
                               backend="onnxruntime", model_size=settings["model_size"],
                               text_score=settings["confidence_threshold"],
                               det_model_path=str(det), rec_model_path=str(rec), cls_model_path=str(cls))
    return EasyOcrOptions(mode=mode, lang=settings["languages"], scale=settings["scale"],
                          confidence_threshold=settings["confidence_threshold"],
                          model_storage_directory=str(models), download_enabled=False)


def download_file(url: str, target: Path, expected: str) -> None:
    from .store import file_sha256
    if target.is_file() and file_sha256(target) == expected:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, prefix=".partial-") as handle:
        partial = Path(handle.name)
        with urlopen(url, timeout=600) as response:
            shutil.copyfileobj(response, handle, 1024 * 1024)
    try:
        if file_sha256(partial) != expected:
            raise ValueError(f"Downloaded {url} does not match its pinned SHA256")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def download_models(models: Path, settings: dict[str, Any]) -> dict[str, str]:
    """Fetch an engine's models while online, verify them, and return their digests."""
    models.mkdir(parents=True, exist_ok=True)
    if settings["engine"] in ("rapidocr", "vietocr"):
        from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel
        for size in {settings["model_size"], "small"}:
            RapidOcrModel.download_models(backend="onnxruntime", local_dir=models / RAPIDOCR_FOLDER,
                                          lang="en", model_size=size)
    if settings["engine"] == "vietocr":
        for name, (url, expected) in VIETOCR_FILES.items():
            download_file(url, models / VIETOCR_FOLDER / name, expected)
    if settings["engine"] == "easyocr":
        import easyocr
        easyocr.Reader(settings["languages"], gpu=False, model_storage_directory=str(models),
                       download_enabled=True, verbose=False)
    return engine_fingerprint(models, settings)["models"]
