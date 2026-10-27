"""Work through the review queue over the API, with a stand-in reviewer.

The real system has a human domain reviewer (design §5.3). This prototype cannot, so two stand-ins exist:
- oracle: accepts a candidate only if it matches a gold fact. It models a careful reviewer who checks every
  claim against the source; real reviewer accuracy and time are not measured by this.
- accept-all: accepts every pending candidate. It models having no review, for comparison.
Both go through the same HTTP review endpoints a UI would use.
"""
from __future__ import annotations

import json
import sys

import httpx

from .config import PROTOTYPE
from .ontology import PROFILE

API = "http://127.0.0.1:8000"


def main(run_id: int, mode: str) -> dict:
    gold = json.loads((PROTOTYPE / "gold/ak3_facts.json").read_text(encoding="utf-8"))["facts"]
    items = httpx.get(f"{API}/review-items", params={"run": run_id}, timeout=60).json()
    tally = {"pending": len(items), "accept": 0, "reject": 0, "conflicts": 0}
    for item in items:
        claim = item["claim"]
        action = "accept" if mode == "accept-all" or any(PROFILE.matches_gold(claim, fact) for fact in gold) else "reject"
        response = httpx.post(f"{API}/review-items/{item['id']}/decisions",
                              json={"action": action, "actor": f"reviewer-{mode}"}, timeout=60)
        if response.status_code == 409:
            tally["conflicts"] += 1
        else:
            response.raise_for_status()
            tally[action] += 1
    # A second decision on an already decided item must be refused.
    if items:
        repeat = httpx.post(f"{API}/review-items/{items[0]['id']}/decisions",
                            json={"action": "accept", "actor": "second-reviewer"}, timeout=60)
        tally["second_decision_refused"] = repeat.status_code == 409
    return tally


if __name__ == "__main__":
    print(json.dumps(main(int(sys.argv[1]), sys.argv[2])))
