"""Rules/v2 emission filters over the unchanged synthetic rules/v1 sentence gates."""
from __future__ import annotations

import re

from kgbuilder.core.well_facts import OBJECT_FIELDS, WellFact, resolve_fact
from kgbuilder.core.well_values import NUMBER, in_name, parse_quantity


RULES_VERSION = "rules/v2"
RULE_RELATIONS = ("reached_td", "drilled_to", "set_casing_at", "casing_size", "set_plug_at", "set_equipment_at",
                  "tagged_at", "cut_at", "tested_to_pressure", "fit_lot_emw", "perforated_interval", "has_mud_weight",
                  "completed_in", "has_well_status", "pumped")
DEPTH = rf"{NUMBER}\s*(?:'|ft\b|feet\b|m\b)(?:\s*(?:MD|TVD|BML|AML|SLM|CTM|WLM|DPM|KBM|RKB|KB)\b)?"
INTERVAL = rf"{NUMBER}\s*(?:'|ft\b|feet\b|m\b)?\s*(?:MD|TVD)?\s*(?:-|to)\s*{DEPTH}"
SIZE = rf'(?:\d+[- ]\d+/\d+|{NUMBER})\s*(?:"|inch(?:es)?\b|in\b)'
PLUG = r"(?:balanced\s+(?:cement\s+)?plug|cement\s+plug|bridge\s+plug|DX\s+plug|XRXX\s+plug|CIBP|TTBP|EZSV|retainer|plug)"
EQUIPMENT = r"(?:isolation\s+packer|packer|(?:X-)?nipple|SCSSV|tubing stop|hanger|BOP|QTS|lubricator|tree|valve)"
TUBULAR = rf"(?:(?:{SIZE})\s*)?(?:casing|csg|liner|conductor|tubing|pipe|stub|SS|LS)\b"
FLUID = r"(?:[A-Za-z]+(?:\s+[A-Za-z]+){0,2}\s+)?(?:cement|mud|brine|slurry|pill)\b"
CUES = (
    ("td", (r"\bTD\b", r"\btotal\s+depth\b")),
    ("drill", (r"\bdrill(?:ed|ing)?\b", r"\bsection\s+TD\b")),
    ("perforate", (r"\bperforat\w*", r"\bperf'd\b", r"\bfired\b")),
    ("test", (r"\btest(?:ed|ing)?\b", r"\bPT\b")),
    ("fit", (r"\b(?:FIT|LOT)\b",)),
    ("set", (r"\b(?:set|landed|ran|placed|spot(?:ted)?|replaced|circ(?:ulated)?|located|noted)\b",)),
    ("tag", (r"\btag(?:ged)?\b",)),
    ("cut", (r"\bcut\b",)),
    ("pump", (r"\b(?:pump(?:ed|ing)?|mixed)\b", r"\bM&P\b")),
    ("bleed", (r"\b(?:bled|bleed(?:ing)?)\b",)),
    ("operate", (r"\boperat\w*",)),
    ("pressure_up", (r"\bpressured\s+up\b",)),
    ("mud", (r"\b(?:MW|mud\s+weight|raised|displac\w*)\b",)),
)


def governing_cue(sentence: str, start: int):
    """Return the nearest completed cue; longer matches win equal-end ties."""
    candidates = [(hit.end(), hit.end() - hit.start(), -i, name)
                  for i, (name, patterns) in enumerate(CUES) for pattern in patterns
                  for hit in re.finditer(pattern, sentence, re.I) if hit.end() <= start]
    if not candidates: return None
    end, _, _, name = max(candidates)
    return name, end


def annotate(doc_id: str, chunk_id: str, text: str) -> list[WellFact]:
    """Emit only sentence-local, explicitly supported facts with exact spans."""
    if not chunk_id.startswith(doc_id + "#"): raise ValueError("chunk/document mismatch")
    facts, seen = [], set()
    sentences = list(re.finditer(r"\S[\s\S]*?(?:(?<=[.!?])(?=\s+[A-Z])|\n|$)", text))
    def span(start, end):
        surface = text[start:end]
        occ, cursor = 0, text.find(surface)
        while cursor != start:
            cursor = text.find(surface, cursor + 1)
            if cursor < 0: raise ValueError("synthetic span construction failed")
            occ += 1
        return {"text": surface, "occ": occ}
    for index, sentence in enumerate(sentences):
        body = sentence[0].rstrip()
        offset = sentence.start()
        evidence = span(offset, offset + len(body))
        attempted = bool(re.search(r"\battempt\w*", body, re.I))
        negative = bool(re.search(r"\b(?:unable|no success|not)\b", body, re.I))
        modality = "attempted" if attempted else "planned" if re.search(r"\b(?:planned|scheduled)\b", body, re.I) else "approved" if re.search(r"\bapproved\b", body, re.I) else "done"
        polarity = "negative" if negative else "positive"
        def find(pattern): return list(re.finditer(pattern, body, re.I))
        intervals = find(INTERVAL)
        depths = [m for m in find(DEPTH) if not any(a.start() <= m.start() < a.end() for a in intervals)]
        def emit(relation, hit, kind, subject=None, stype="Borehole", qualifiers=None):
            # Suppress only the hit v1 selected; never expose or select a farther quantity.
            if kind in {"depth", "interval"} and in_name(text, offset + hit.start(), offset + hit.end()): return
            required = {"reached_td": "td", "drilled_to": "drill", "perforated_interval": "perforate",
                        "fit_lot_emw": "fit", "tested_to_pressure": "test"}.get(relation)
            if required:
                cue = governing_cue(body, hit.start())
                if cue is None or cue[0] != required: return
                if relation == "tested_to_pressure" and not re.search(r"\bto\b|@", body[cue[1]:hit.start()], re.I): return
            obj = {"kind": kind, **span(offset + hit.start(), offset + hit.end())}
            if kind in {"entity", "status"}:
                obj.update({"type": "Zone"} if kind == "entity" else {"value": qualifiers.pop("status")})
            else:
                q = parse_quantity(hit[0], kind)
                if q.status != "ok": return
                obj.update({key: getattr(q, key) for key in OBJECT_FIELDS[kind]})
            subj = {"implicit": "report_well", "type": "Borehole"} if subject is None else {
                **span(offset + subject.start(), offset + subject.end()), "type": stype}
            identity = (relation, obj["text"], obj["occ"], str(subj))
            if identity in seen: return
            seen.add(identity)
            fact = WellFact(annotator=RULES_VERSION, chunk_id=chunk_id, fact_no=len(facts) + 1, relation=relation,
                            subject=subj, object=obj, qualifiers=qualifiers or {}, polarity=polarity, modality=modality,
                            time=None, uncertainty="certain", evidence=evidence,
                            note=subject[0].lower() if relation == "tagged_at" and subject is not None and subject[0].lower() in {"toc", "fill", "fish", "obstruction"} else "")
            facts.append(resolve_fact(fact, text))
        tubulars, plugs, equipment = find(TUBULAR), find(PLUG), find(EQUIPMENT)
        for tubular in tubulars:
            sizes = list(re.finditer(SIZE, body[:tubular.end()], re.I))
            if sizes and sizes[-1].start() >= tubular.start(): emit("casing_size", sizes[-1], "size", tubular, "Tubular")
        def next_quantity(noun, allowed):
            return next((m for m in sorted(allowed, key=lambda m: m.start()) if m.start() >= noun.end()), None)
        if re.search(r"\b(?:set|placed|spot(?:ted)?|replaced|circ(?:ulated)?)\b", body, re.I):
            for noun in plugs:
                hit = next_quantity(noun, intervals + depths)
                if hit and re.search(r"\b(?:at|from|to)\b|@", body[noun.end():hit.start()], re.I):
                    action = "replaced" if re.search(r"\breplaced\b", body, re.I) else "placed" if re.search(r"\b(?:placed|spotted|circ(?:ulated)?)\b", body, re.I) else "set"
                    emit("set_plug_at", hit, "interval" if hit in intervals else "depth", noun, "Plug", {"action": action})
        if re.search(r"\b(?:set|landed|located|noted)\b", body, re.I):
            # A nipple named only as the location of a plug does not assert equipment placement.
            if not plugs:
                for noun in equipment:
                    hit = next_quantity(noun, depths)
                    if hit: emit("set_equipment_at", hit, "depth", noun, "Equipment", {"action": "located" if re.search(r"\b(?:located|noted)\b", body, re.I) else "set"})
        if re.search(r"\b(?:set|landed|ran)\b", body, re.I):
            for noun in tubulars:
                if re.search(SIZE, noun[0], re.I):
                    hit = next_quantity(noun, depths)
                    if hit: emit("set_casing_at", hit, "depth", noun, "Tubular")
        if re.search(r"\b(?:test(?:ed)?|PT)\b", body, re.I):
            nouns = sorted([(n, "Tubular") for n in tubulars] + [(n, "Plug") for n in plugs] + [(n, "Equipment") for n in equipment], key=lambda v: v[0].start())
            for pressure in find(rf"{NUMBER}\s*(?:psig?\b|#)"):
                if not re.search(r"\bto\b|@", body[:pressure.start()], re.I): continue
                chosen = next(((n, t) for n, t in reversed(nouns) if n.end() <= pressure.start()), None)
                if chosen is None: continue
                noun, stype = chosen
                qualifiers = {"test_kind": "tubing" if "tubing" in noun[0].lower() else "casing" if re.search(r"casing|csg", noun[0], re.I) else "plug" if stype == "Plug" else "lubricator" if noun[0].lower() in {"qts", "lubricator"} else "bop" if "bop" in noun[0].lower() else "other"}
                following = body + (" " + sentences[index + 1][0] if index + 1 < len(sentences) else "")
                if re.search(r"good test", following, re.I): qualifiers["result"] = "good"
                elif re.search(r"bled down|bleed down", following, re.I): qualifiers["result"] = "failed"
                emit("tested_to_pressure", pressure, "pressure", noun, stype, qualifiers)
        if re.search(r"\b(?:perforat\w*|perf'd|fired\b.*\bgun)\b", body, re.I):
            for hit in intervals + depths: emit("perforated_interval", hit, "interval" if hit in intervals else "depth")
        for relation, cue, nouns in (("tagged_at", r"\btag(?:ged)?\b", [(n, "Plug") for n in plugs] + [(n, "Equipment") for n in find(r"\b(?:TOC|fill|fish|obstruction)\b")]),
                                     ("cut_at", r"\bcut\b", [(n, "Tubular") for n in tubulars] + [(n, "Equipment") for n in equipment])):
            if re.search(cue, body, re.I):
                for noun, stype in nouns:
                    hit = next_quantity(noun, depths)
                    if hit:
                        qualifiers = {"bound": "ge"} if relation == "cut_at" and "at least" in body.lower() else {}
                        emit(relation, hit, "depth", noun, stype, qualifiers)
        td = re.search(r"\b(?:TD|total depth)\b", body, re.I)
        section = bool(re.search(r"\bsection\s+TD\b", body, re.I))
        if td and not section:
            for hit in depths:
                if hit.start() >= td.end(): emit("reached_td", hit, "depth")
        if section or re.search(r"\bdrill(?:ed)?\b.*\bto\b", body, re.I):
            for hit in depths:
                if not section or hit.start() >= re.search(r"\bsection\s+TD\b", body, re.I).end(): emit("drilled_to", hit, "depth")
        densities = find(rf"{NUMBER}\s*(?:ppg\b|lb/gal\b|EMW\b)")
        if re.search(r"\b(?:FIT|LOT)\b", body, re.I):
            for hit in densities: emit("fit_lot_emw", hit, "density", qualifiers={"test_kind": re.search(r"\b(FIT|LOT)\b", body, re.I)[1].lower()})
        if densities and re.search(r"\b(?:MW|mud weight|raised|displace\w*)\b", body, re.I) and re.search(r"\bto\b", body, re.I):
            emit("has_mud_weight", densities[-1], "density")
        if re.search(r"\b(?:pumped|mixed and pumped)\b|M&P", body, re.I):
            for hit in find(rf"{NUMBER}\s*(?:bbls?\b|sx\b|cu\s*ft\b|gal\b)"):
                noun = next(re.compile(FLUID, re.I).finditer(body, hit.end()), None)
                if noun: emit("pumped", hit, "volume", noun, "Fluid")
        for hit in find(r"\b(?:re)?complet\w*\s+(?:in|to)\s+(?:the\s+)?(?P<zone>[A-Za-z0-9()/-]+(?:\s+[A-Za-z0-9()/-]+){0,3}\s+(?:sand|zone|reservoir))\b"):
            # Re-search at the known interval to retain sentence-relative offsets.
            zone = next(m for m in re.finditer(re.escape(hit["zone"]), body) if m.start() >= hit.start())
            emit("completed_in", zone, "entity")
        status_patterns = {"TA": r"\b(?:TA'd|T/A|temporarily abandoned|temporary abandonment)\b", "PA": r"\b(?:P&A|permanently abandoned)\b",
                           "ST": r"\b(?:sidetrack(?:ed)?|plugged back)\b", "COM": r"\b(?:completed|recompleted)\b", "BP": r"\bbypass(?:ed)?\b", "SI": r"\bshut[ -]in\b"}
        for status, pattern in status_patterns.items():
            for hit in find(pattern):
                if status == "COM" and re.search(r"\b(?:test|operations)\b", body, re.I): continue
                emit("has_well_status", hit, "status", qualifiers={"status": status})
    return facts
