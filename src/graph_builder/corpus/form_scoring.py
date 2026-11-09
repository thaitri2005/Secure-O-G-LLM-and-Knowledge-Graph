"""Score extracted key-value pairs against reviewed annotations."""
from __future__ import annotations

from collections import Counter

from graph_builder.ingestion.scoring import bbox_iou


def whitespace(text: str) -> str:
    return " ".join(text.split())


def pair_score(expected: list, actual: list, reference: str) -> dict:
    """Compare (key, value) pairs as multisets; extra predictions lower accuracy, values absent from the source are listed."""
    gold = Counter((whitespace(key), whitespace(value)) for key, value in expected)
    pred = Counter((whitespace(field["key"]), whitespace(field["value"])) for field in actual)
    matched, union = sum((gold & pred).values()), sum((gold | pred).values())
    invented = [field["value"] for field in actual if whitespace(field["value"]) and whitespace(field["value"]) not in whitespace(reference)]
    boxes = sum(bool(field.get("key_bbox")) and (not field["value"] or bool(field.get("value_bbox"))) for field in actual)
    return dict(matched=matched, gold_pairs=sum(gold.values()), predicted_pairs=sum(pred.values()),
                pair_accuracy=matched / union if union else None,
                pair_recall=matched / sum(gold.values()) if gold else None,
                pair_precision=matched / sum(pred.values()) if pred else None,
                literal_source_absent_values=invented, literal_source_absent_count=len(invented),
                bbox_pairs=boxes, bbox_share=boxes / len(actual) if actual else None,
                errors=[dict(key=key, value=value, missing=count) for (key, value), count in (gold - pred).items()])


def annotated_box_coverage(expected: list[dict], actual: list[dict]) -> dict:
    """Match duplicate pairs spatially and measure reviewed key/value box overlap."""
    remaining = list(actual)
    overlaps = []
    for field in expected:
        candidates = [p for p in remaining if (whitespace(p["key"]), whitespace(p["value"])) ==
                      (whitespace(field["key"]), whitespace(field["value"]))]
        selected = max(candidates, key=lambda p: bbox_iou(p["key_bbox"], field["key_bbox"]), default=None)
        if selected:
            remaining.remove(selected)
        for key in ("key_bbox", "value_bbox"):
            if field.get(key):
                overlaps.append(bbox_iou(field[key], selected[key]) if selected and selected.get(key) else 0.0)
    return {"annotated_boxes": len(overlaps), "boxes_with_positive_overlap": sum(value > 0 for value in overlaps),
            "annotated_bbox_coverage": sum(value > 0 for value in overlaps) / len(overlaps) if overlaps else None,
            "mean_matched_bbox_iou": sum(overlaps) / len(overlaps) if overlaps else None}
