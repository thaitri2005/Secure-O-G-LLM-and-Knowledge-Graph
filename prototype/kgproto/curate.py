"""Duplicate search for one extraction run (design §5.9, FR-21): suggestions for a person, nothing is merged.

Lists the subject names the model produced in the run's validated candidates, grouped by the profile's match
key ("AK-3", "Akutan Well AK-3" and "ak 3" are one key), and pairs of different keys that look alike.
"""
from __future__ import annotations

import json
import sys

from .db import connect
from .ontology import PROFILE


def main(run_id: int, threshold: float = 0.8) -> dict:
    rows = connect().execute("SELECT claim FROM candidates WHERE run_id = %s AND valid", (run_id,)).fetchall()
    names = [claim[PROFILE.subject_field] for (claim,) in rows]
    return {"run_id": run_id, "profile": PROFILE.id, "mentions": len(names), "distinct_names": len(set(names)),
            "suggestions": PROFILE.duplicate_pairs(names, threshold)}


if __name__ == "__main__":
    print(json.dumps(main(int(sys.argv[1]), *(float(a) for a in sys.argv[2:3])), indent=2))
