"""Answers with retrieval bypassed: the model gets the page each gold value was written from (E24).

This separates the layers of a failure. A question missed here is not a retrieval failure; a question answered
here and missed by a real retriever is. A diagnostic, not a pipeline: it reads the gold data.

    python -m graphrag.oracle --answer-format evidence_first --max-tokens 700 --name E24_oracle_evidence
"""
from __future__ import annotations

import argparse
import json

from .baseline import ANSWER_FORMATS, RESULTS, answer_questions, build, pool, summarize
from .client import ModelClient, load_endpoints
from .data import daily_rows, load_questions

# The attachment each gold value was read from: the summary report, unless it prints the value only elsewhere.
SOURCE_ATTACHMENT = {"d05": "28", "d06": "29", "d07": "29"}
DEFAULT_ATTACHMENT = "30"


def attachment(doc_id: str) -> str:
    return doc_id.split("-appx-")[1][:2]


def source_chunks(question: dict, gold: dict, rows: list[dict]) -> list[str]:
    """Chunks on the pages of the attachment the question's gold values were read from."""
    wanted = SOURCE_ATTACHMENT.get(question["id"], DEFAULT_ATTACHMENT)
    pages = {s["page"] for g in question["gold"] for s in gold[g]["sources"] if s["appx"] == wanted}
    return [r["chunk_id"] for r in rows if attachment(r["doc_id"]) == wanted and set(r["pages"]) & pages]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--endpoint", default="local-llama")
    parser.add_argument("--model", default="qwen3-8b")
    parser.add_argument("--max-tokens", type=int, default=400)
    parser.add_argument("--answer-format", choices=ANSWER_FORMATS, default="status_first")
    parser.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    chunks, rows = pool("ak3_daily"), daily_rows()
    questions, gold = load_questions("ak3_daily")
    by_text = {q["question"]: q for q in questions}
    # Must-not-answer questions have no source page, so they get what the baseline retriever finds.
    fallback = build("wells:bm25", chunks)

    def retrieve(question: str) -> tuple[list[str], str]:
        q = by_text[question]
        return (source_chunks(q, gold, rows) if q["gold"] else [c for c, _ in fallback.search(question, 5)]), ""

    client = ModelClient(load_endpoints()[args.endpoint], args.model)
    result = summarize(answer_questions(retrieve, chunks, client, questions="ak3_daily", max_tokens=args.max_tokens,
                                        answer_format=args.answer_format), client)
    result = {"pool": "ak3_daily", "retriever": "oracle: the gold value's source page", "question_set": "ak3_daily",
              "endpoint": args.endpoint, "model": args.model, "answer_format": args.answer_format, **result}
    (RESULTS / f"{args.name}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(result["correct_total"], result["correct_by_kind"])


if __name__ == "__main__":
    main()
