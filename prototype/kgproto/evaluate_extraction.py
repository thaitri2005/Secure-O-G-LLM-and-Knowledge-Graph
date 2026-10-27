"""Score one extraction run before review: validated candidates against the gold facts in scope."""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter

from .config import PROTOTYPE, RESULTS
from .db import connect
from .ontology import PROFILE

matches_gold = PROFILE.matches_gold


def evaluate(run_id: int) -> dict:
    db = connect()
    gold = json.loads((PROTOTYPE / "gold/ak3_facts.json").read_text(encoding="utf-8"))["facts"]
    rows = db.execute("SELECT chunk_id, claim, valid, reason, latency_ms, output_ok FROM candidates WHERE run_id = %s",
                      (run_id,)).fetchall()
    processed = sorted({r[0] for r in rows})
    in_scope = [f for f in gold if set(f["chunks"]) & set(processed)]
    claims = [(r[0], r[1]) for r in rows if r[1] is not None]
    accepted = [(chunk, claim) for (chunk, claim), r in zip(claims, [r for r in rows if r[1] is not None]) if r[2]]
    found = {f["id"] for f in in_scope if any(matches_gold(c, f) for _, c in accepted)}
    false_positives = [{"chunk": chunk, **{k: claim.get(k) for k in ("well", "property", "qualifier", "value",
                                                                      "casing_size_in", "depth_ft")}}
                       for chunk, claim in accepted if not any(matches_gold(claim, f) for f in in_scope)]
    latencies = sorted({(r[0], r[4]) for r in rows})
    true_accepted = len(accepted) - len(false_positives)
    result = {
        "run_id": run_id, "chunks": len(processed), "gold_facts_in_scope": len(in_scope),
        "model_outputs_parsed": f"{sum(1 for c, l in latencies)}/{len(latencies)}"
                                if all(r[5] for r in rows) else "some outputs unparseable",
        "candidates": len(claims), "passed_validation": len(accepted),
        "rejection_reasons": dict(Counter(r[3] for r in rows if r[1] is not None and not r[2])),
        "precision_strict": round(true_accepted / len(accepted), 3) if accepted else None,
        "recall": round(len(found) / len(in_scope), 3) if in_scope else None,
        "gold_found": len(found), "gold_missed": sorted(f["id"] for f in in_scope if f["id"] not in found),
        "false_positives": false_positives,
        "latency_s_per_chunk": {"median": round(statistics.median(l for _, l in latencies) / 1000, 1),
                                "max": round(max(l for _, l in latencies) / 1000, 1),
                                "total": round(sum(l for _, l in latencies) / 1000, 1)},
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"extraction_run{run_id}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(evaluate(int(sys.argv[1])), indent=2))
