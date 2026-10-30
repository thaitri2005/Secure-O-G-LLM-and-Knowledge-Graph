"""Versioned statement conversion using only the frozen literal and v1 parsers."""
from __future__ import annotations

from kgbuilder.core import well_facts, well_literals
from kgbuilder.core.well_facts import WellFact


CONVERTER_VERSION = "v2"
TYPED_KINDS = frozenset(well_literals.QUANTITY_KINDS) | {"date"}


def _statement(graph: dict, statement: dict, doc_ids: set[str], lexicon: dict):
    single = {**graph, "statements": [statement]}
    original = well_facts.facts_from_graph(single, doc_ids)
    relation = statement["predicate"]
    if not original or relation not in well_facts.RELATION_SPEC or relation == "casing_spec":
        return original, "unchanged"
    surface = original[0].object["text"]
    kinds = set(well_facts.RELATION_SPEC[relation][1])
    kind = original[0].object["kind"]
    if "status" in kinds and kind != "status":
        code = well_literals.status_code(surface, lexicon["status"])
        if code is not None:
            obj = {"kind": "status", "text": surface, "occ": 0, "value": code}
            return [f.model_copy(update={"object": dict(obj)}) for f in original], "C2"
    typed = kinds & TYPED_KINDS
    spans = list(dict.fromkeys(text.strip() for _, _, text in well_literals.typed_spans(surface, typed)))
    if not spans or (kind in kinds and len(spans) <= 1):
        return original, "unchanged"
    converted = []
    for span in spans:
        entities = [{**e, "name": span} if e["entity_id"] == statement["object_id"] else e
                    for e in graph["entities"]]
        facts = well_facts.facts_from_graph({**single, "entities": entities}, doc_ids)
        # A resolved entity can occupy both slots; only the object is converted.
        converted.extend(f.model_copy(update={"subject": old.subject}) for f, old in zip(facts, original))
    return converted, "C1" if len(spans) == 1 else "C3"


def facts_from_graph_v2(graph: dict, doc_ids: set[str], lexicon: dict) -> list[WellFact]:
    """Apply C1-C3 per statement, retaining occurrence and statement order."""
    output = []
    for statement in graph["statements"]:
        facts, _ = _statement(graph, statement, doc_ids, lexicon)
        for fact in facts:
            output.append(fact.model_copy(update={"fact_no": len(output) + 1}))
    return output


def conversion_counts(graph: dict, doc_ids: set[str], lexicon: dict) -> dict:
    """Count accepted in-scope statements, not expanded facts."""
    counts = dict.fromkeys(("statements", "unchanged", "C1", "C2", "C3"), 0)
    for statement in graph["statements"]:
        facts, rule = _statement(graph, statement, doc_ids, lexicon)
        if facts:
            counts["statements"] += 1
            counts[rule] += 1
    return counts
