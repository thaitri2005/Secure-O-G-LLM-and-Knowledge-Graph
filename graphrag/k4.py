"""K4 answer records (specification §4.5, B to C) from a Track B answer run.

    python -m graphrag.k4 E22_prototype_wells-bm25_k5_sheet-llm-tables_top3

Writes `graphrag/results/<run>.k4.jsonl`, one record per question, valid against
`schemas/k4_answer_record.schema.json`. Per-question cost is the answer call; index-time cost (extraction,
embeddings) is in the run's result file and its experiment record.
"""
from __future__ import annotations

import argparse
import json

from .baseline import RESULTS
from .data import ROOT, load_questions

SCHEMA = ROOT / "schemas/k4_answer_record.schema.json"


def records(run: str) -> list[dict]:
    result = json.loads((RESULTS / f"{run}.json").read_text(encoding="utf-8"))
    question_set = result.get("question_set", "prototype")
    text = {q["id"]: q["question"] for q in load_questions(question_set)[0]}
    model = (result["cost"].get("models") or [f"{result.get('endpoint', '?')}:{result['model']}"])[0]
    pipeline = {"base": "lightrag" if "index" in result else "plain_rag",
                "retriever": result.get("retriever") or f"lightrag:{result.get('mode')}",
                "k": result.get("k"), "fact_sheet": result.get("fact_sheet"),
                "validated": bool(result.get("validated")), "answer_format": result.get("answer_format", "status_first")}
    out = []
    for row in result["rows"]:
        units = row.get("units") or [None] * len(row["values"])
        out.append({
            "k4_version": "0.1", "run": run, "question_set": question_set, "question_id": row["id"],
            "question": text.get(row["id"], ""), "status": row["status"],
            "answers": [{"value": str(v), **({"unit": u} if u else {})} for v, u in zip(row["values"], units)],
            "citations": [{"chunk_id": c["chunk"], "how": c["how"]} for c in row["citations"]],
            "pipeline": {k: v for k, v in pipeline.items() if v is not None},
            "models": {"answer": model},
            "cost": {"calls": 1, "prompt_tokens": row["prompt_tokens"], "completion_tokens": row["completion_tokens"],
                     "seconds": row["seconds"], "cost_usd": 0.0 if model.startswith("local") else row.get("cost_usd", 0.0)},
            "correct": row["correct"]})
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", help="an answer-run result name under graphrag/results/")
    args = parser.parse_args(argv)
    rows = records(args.run)
    path = RESULTS / f"{args.run}.k4.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n")
    print(f"{len(rows)} K4 records written to {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
