"""Docling OCR engine: PP-OCRv6 text-line detection (RapidOCR, ONNX) with VietOCR transformer recognition.

VietOCR recognizes Vietnamese with all tone marks as well as English, digits and punctuation; the
PP-OCR recognizers drop most precomposed Vietnamese letters. Detection and recognition both run on CPU
from pinned local files and never download anything.
"""
from __future__ import annotations

from collections import defaultdict
import logging
import math
from pathlib import Path
from typing import ClassVar, Iterable, Literal, Type

import numpy

from docling.datamodel.pipeline_options import OcrOptions
from docling.models.base_ocr_model import BaseOcrModel

_log = logging.getLogger(__name__)
KIND = "graph_builder_vietocr"


class VietOcrOptions(OcrOptions):
    kind: ClassVar[Literal["graph_builder_vietocr"]] = KIND
    canonicalize_lang: ClassVar[bool] = False
    lang: list[str] = ["vi", "en"]
    det_model_path: str
    weights_path: str
    config_dir: str
    image_height: int = 32
    image_max_width: int = 512
    batch_size: int = 32
    det_box_thresh: float = 0.5
    det_max_side: int = 1600
    num_threads: int | None = None


class VietOcrModel(BaseOcrModel):
    def __init__(self, enabled: bool, artifacts_path: Path | None, options: VietOcrOptions, accelerator_options):
        super().__init__(enabled=enabled, artifacts_path=artifacts_path, options=options,
                         accelerator_options=accelerator_options)
        self.options: VietOcrOptions
        self.scale = options.scale
        if not enabled:
            return
        import torch
        import yaml
        from rapidocr import RapidOCR
        from vietocr.tool.translate import build_model

        for path in (options.det_model_path, options.weights_path):
            if not Path(path).is_file():
                raise FileNotFoundError(f"VietOCR engine file missing: {path}")
        threads = options.num_threads or accelerator_options.num_threads
        torch.set_num_threads(max(1, threads))
        config_dir = Path(options.config_dir)
        config = yaml.safe_load((config_dir / "base.yml").read_text(encoding="utf-8"))
        config.update(yaml.safe_load((config_dir / "vgg-transformer.yml").read_text(encoding="utf-8")))
        config["device"] = "cpu"
        config["cnn"]["pretrained"] = False  # weights come from the pinned checkpoint, not torchvision
        self.model, self.vocab = build_model(config)
        self.model.load_state_dict(torch.load(options.weights_path, map_location="cpu", weights_only=True))
        self.model.eval()
        # RapidOCR loads a recognizer even when only detection runs; point it at the local detector's sibling.
        folder = Path(options.det_model_path).parent
        self.detector = RapidOCR(params={
            "Global.log_level": "error",
            "Det.model_path": options.det_model_path,
            "Det.box_thresh": options.det_box_thresh,
            # Detection cost grows with image area; cap the longer side (pixels) on small CPUs.
            "Det.limit_type": "max",
            "Det.limit_side_len": options.det_max_side,
            "Cls.model_path": str(folder / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"),
            "Rec.model_path": str(folder / "PP-OCRv6_rec_small.onnx"),
            "EngineConfig.onnxruntime.intra_op_num_threads": max(1, threads),
        })

    @classmethod
    def get_options_type(cls) -> Type[OcrOptions]:
        return VietOcrOptions

    def map_ocr_language(self, language) -> str:
        return language.tag()

    def detect(self, image) -> list[tuple[float, float, float, float]]:
        result = self.detector(numpy.asarray(image), use_det=True, use_cls=False, use_rec=False)
        if result is None or result.boxes is None:
            return []
        boxes = []
        for quad in result.boxes.tolist():
            xs, ys = [point[0] for point in quad], [point[1] for point in quad]
            if max(xs) - min(xs) >= 2 and max(ys) - min(ys) >= 2:
                boxes.append((min(xs), min(ys), max(xs), max(ys)))
        return boxes

    def recognize(self, crops: list) -> list[tuple[str, float]]:
        """Recognize line images in batches of equal resized width (VietOCR pads nothing)."""
        import torch
        from vietocr.tool.translate import process_input, translate

        height, max_width = self.options.image_height, self.options.image_max_width
        buckets: dict[int, list[int]] = defaultdict(list)
        tensors = []
        for index, crop in enumerate(crops):
            tensor = process_input(crop, height, 32, max_width)
            tensors.append(tensor)
            buckets[tensor.shape[-1]].append(index)
        results: list[tuple[str, float]] = [("", 0.0)] * len(crops)
        for indices in buckets.values():
            for start in range(0, len(indices), self.options.batch_size):
                batch = indices[start:start + self.options.batch_size]
                with torch.inference_mode():
                    sequences, probabilities = translate(torch.cat([tensors[i] for i in batch]), self.model)
                for position, index in enumerate(batch):
                    text = self.vocab.decode(sequences[position].tolist())
                    probability = float(probabilities[position])
                    results[index] = (text, 0.0 if math.isnan(probability) else probability)
        return results

    def __call__(self, conv_res, page_batch: Iterable):
        from docling.utils.profiling import TimeRecorder
        from docling_core.types.doc import BoundingBox, CoordOrigin
        from docling_core.types.doc.page import BoundingRectangle, TextCell

        if not self.enabled:
            yield from page_batch
            return
        for page in page_batch:
            if page._backend is None or not page._backend.is_valid():
                yield page
                continue
            with TimeRecorder(conv_res, "ocr"):
                cells = []
                for rect in self.get_ocr_rects(page):
                    if rect.area() == 0:
                        continue
                    image = page._backend.get_page_image(scale=self.scale, cropbox=rect).convert("RGB")
                    boxes = self.detect(image)
                    crops = []
                    for left, top, right, bottom in boxes:
                        pad = (bottom - top) * 0.15
                        crops.append(image.crop((max(0, left - pad), max(0, top - pad),
                                                 min(image.width, right + pad), min(image.height, bottom + pad))))
                    for (left, top, right, bottom), (text, confidence) in zip(boxes, self.recognize(crops)):
                        if not text.strip():
                            continue
                        cells.append(TextCell(
                            index=len(cells), text=text, orig=text, confidence=confidence, from_ocr=True,
                            rect=BoundingRectangle.from_bounding_box(BoundingBox.from_tuple(
                                coord=(left / self.scale + rect.l, top / self.scale + rect.t,
                                       right / self.scale + rect.l, bottom / self.scale + rect.t),
                                origin=CoordOrigin.TOPLEFT))))
                    del image
                self.post_process_cells(cells, page, conv_res)
            yield page


def register() -> None:
    """Make the engine available to Docling's OCR factory in this process (idempotent)."""
    from docling.models.factories import get_ocr_factory
    for allow in (False, True):
        factory = get_ocr_factory(allow_external_plugins=allow)
        if VietOcrOptions not in factory.classes:
            factory.register(VietOcrModel, "graph_builder", __name__)
