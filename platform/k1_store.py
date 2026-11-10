"""Read K1 chunks back from the Track C PostgreSQL (C-C09): the door through which Track B reads the store.

    python platform/k1_store.py compare data/interim/k1/ak3-k1v1-proposed     # store equals the package?
    python platform/k1_store.py export --out data/interim/k1/chunks.jsonl     # chunks.jsonl written from the store

`read_chunks()` returns the chunk records of one release exactly as the package's chunks.jsonl holds them, in the
package's order, so `graphrag` can read the store with no other change. `export` writes them as a chunks.jsonl,
which `graphrag` already reads (`GRAPHRAG_K1_CHUNKS`). Needs psycopg (see platform/load_k1.py).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import psycopg

DSN = "postgresql://kg:platform-dev@127.0.0.1:5434/kg"   # platform/docker-compose.yml


def only_release(cur) -> str:
    """The release to read when none is named: the store must hold exactly one."""
    cur.execute("SELECT release FROM k1_releases ORDER BY release")
    releases = [row[0] for row in cur.fetchall()]
    if len(releases) != 1:
        raise SystemExit(f"name a release with --release; the store holds {releases or 'none'}")
    return releases[0]


def read_chunks(release: str | None = None, dsn: str = DSN) -> list[dict]:
    """The chunk records of a release, as the package wrote them, in reading order (chunks.seq)."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        release = release or only_release(cur)
        cur.execute("SELECT c.record FROM chunks c JOIN files f USING (file_id) WHERE f.release = %s ORDER BY c.seq",
                    (release,))
        return [row[0] for row in cur.fetchall()]


def compare(stored: list[dict], package: list[dict]) -> list[str]:
    """Differences between the stored records and the package's, position by position; empty when identical."""
    problems = []
    if len(stored) != len(package):
        problems.append(f"{len(stored)} chunks in the store, {len(package)} in the package")
    for n, (a, b) in enumerate(zip(stored, package)):
        if a != b:
            fields = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
            problems.append(f"line {n + 1} ({b.get('chunk_id')}): differs in {', '.join(fields)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn", default=DSN)
    parser.add_argument("--release", help="release in the store (default: the only one)")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("compare", help="check that the store holds the package's chunks unchanged")
    check.add_argument("package", type=Path, help="K1 release folder")
    out = commands.add_parser("export", help="write the store's chunks as a chunks.jsonl")
    out.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    stored = read_chunks(args.release, args.dsn)
    if args.command == "compare":
        lines = (args.package / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        package = [json.loads(line) for line in lines if line.strip()]
        problems = compare(stored, package)
        same = sum(a == b for a, b in zip(stored, package))
        print(f"{same} / {len(package)} chunks identical between the store and {args.package}")
        print(*problems[:10], sep="\n")
        return 1 if problems else 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        for record in stored:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"wrote {len(stored)} chunks to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
