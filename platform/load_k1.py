"""Load one K1 version 1 package into the Track C PostgreSQL (C-C08).

    python platform/load_k1.py data/interim/k1/ak3-k1v1-proposed

Steps, all or nothing:
1. Check the package with Track A's validator (graph_builder.corpus.k1_validate); refuse it on any error.
2. In one transaction, delete the release if it was loaded before, then insert its files, pages, parents, tables,
   forms, chunks (in reading order) and, when present, the map from version 0 chunk IDs.
3. Read everything back from the database and check it: row counts equal the manifest's, and every page rebuilds
   from the stored chunks to the digest the package recorded. Any difference rolls the load back.

The tables are in platform/sql/001_k1.sql. Needs psycopg (pip install "psycopg[binary]==3.3.8") and the four
packages Track A's validator imports (docs/tracks/C-storage/log.md, C-C08).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from graph_builder.corpus.k1_validate import GROUPS, LEGACY_MAP, MANIFEST, SUMS, rebuild_pages, validate_k1  # noqa: E402

DSN = "postgresql://kg:platform-dev@127.0.0.1:5434/kg"   # platform/docker-compose.yml
TABLE = {"files": "files", "pages": "pages", "parents": "parents", "tables": "k1_tables", "forms": "forms",
         "chunks": "chunks"}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_package(directory: Path) -> dict:
    package = {name: read_jsonl(directory / f"{name}.jsonl") for name in GROUPS}
    package["manifest"] = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    package["sums_sha256"] = hashlib.sha256((directory / SUMS).read_bytes()).hexdigest()
    legacy = directory / LEGACY_MAP
    package["legacy"] = json.loads(legacy.read_text(encoding="utf-8")) if legacy.is_file() else []
    return package


def insert(cur, sql: str, rows: list[tuple]) -> None:
    if rows:
        cur.executemany(sql, rows)


def load(cur, release: str, package: dict) -> None:
    """Replace the release in the database with the package's rows."""
    cur.execute("DELETE FROM k1_releases WHERE release = %s", (release,))
    manifest = package["manifest"]
    cur.execute("INSERT INTO k1_releases (release, schema_version, manifest, sha256sums_sha256) VALUES (%s, %s, %s, %s)",
                (release, manifest.get("schema_version", "unknown"), Jsonb(manifest), package["sums_sha256"]))
    insert(cur, "INSERT INTO files (file_id, release, doc_id, document_type, sha256, page_count, record) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
           [(r["file_id"], release, r["doc_id"], r["document_type"], r["sha256"], r["page_count"], Jsonb(r))
            for r in package["files"]])
    insert(cur, "INSERT INTO pages (page_id, file_id, page, status, filtered_text_sha256, record) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
           [(r["page_id"], r["file_id"], r["page"], r["status"], r["filtered_text_sha256"], Jsonb(r))
            for r in package["pages"]])
    insert(cur, "INSERT INTO parents (parent_id, file_id, type, pages, document_type, record) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
           [(r["parent_id"], r["file_id"], r["type"], r["pages"], r["document_type"], Jsonb(r))
            for r in package["parents"]])
    insert(cur, "INSERT INTO k1_tables (table_id, file_id, logical_id, pages, num_rows, num_cols, record) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
           [(r["table_id"], r["file_id"], r["logical_id"], r["pages"], r["num_rows"], r["num_cols"], Jsonb(r))
            for r in package["tables"]])
    insert(cur, "INSERT INTO forms (form_id, file_id, page, verified, record) VALUES (%s, %s, %s, %s, %s)",
           [(r["form_id"], r["file_id"], r["page"], r["verified"], Jsonb(r)) for r in package["forms"]])
    insert(cur, "INSERT INTO chunks (chunk_id, parent_id, file_id, table_id, form_id, type, child_index, seq, page, "
                "pages, text, sha256, quality, well, report_date, record) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
           [(r["chunk_id"], r["parent_id"], r["file_id"], r["table_id"], r["form_id"], r["type"], r["child_index"],
             seq, r["page"], r["pages"], r["text"], r["sha256"], r["quality"], r["context"].get("well"),
             r["context"].get("report_date"), Jsonb(r))
            for seq, r in enumerate(package["chunks"])])
    insert(cur, "INSERT INTO chunk_id_map (old_chunk_id, release, chunk_id, method, jaccard) VALUES (%s, %s, %s, %s, %s)",
           [(r["old_chunk_id"], release, r["new_chunk_id"], r["method"], r.get("jaccard")) for r in package["legacy"]])


def check(cur, release: str, package: dict) -> list[str]:
    """Problems found when reading the release back; empty when the database holds the package unchanged."""
    problems = []
    for name, table in TABLE.items():
        cur.execute(f"SELECT count(*) FROM {table} t JOIN files f USING (file_id) WHERE f.release = %s"
                    if name != "files" else "SELECT count(*) FROM files WHERE release = %s", (release,))
        count = cur.fetchone()[0]
        expected = package["manifest"]["counts"][name]
        if count != expected:
            problems.append(f"{table}: {count} rows in the database, manifest says {expected}")
    cur.execute("SELECT p.record FROM pages p JOIN files f USING (file_id) WHERE f.release = %s", (release,))
    pages = [row[0] for row in cur.fetchall()]
    cur.execute("SELECT c.record FROM chunks c JOIN files f USING (file_id) WHERE f.release = %s ORDER BY c.seq",
                (release,))
    chunks = [row[0] for row in cur.fetchall()]
    matches, total = rebuild_pages({"pages": pages, "chunks": chunks}, problems)
    print(f"page rebuild from the database: {matches} / {total}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("package", type=Path, help="K1 release folder (the one holding manifest.json)")
    parser.add_argument("--release", help="release name in the database (default: the folder name)")
    parser.add_argument("--dsn", default=DSN, help=f"PostgreSQL connection (default: {DSN})")
    args = parser.parse_args(argv)
    release = args.release or args.package.resolve().name

    errors = validate_k1(args.package)
    if errors:
        print(f"refused: Track A's validator found {len(errors)} problems", *errors[:10], sep="\n  ")
        return 1
    package = read_package(args.package)
    print(f"package {release}: valid; " + ", ".join(f"{name} {len(package[name])}" for name in GROUPS)
          + f", legacy map {len(package['legacy'])}")

    with psycopg.connect(args.dsn) as conn:          # one transaction: committed only if every check passes
        with conn.cursor() as cur:
            load(cur, release, package)
            problems = check(cur, release, package)
        if problems:
            conn.rollback()
            print(f"rolled back: {len(problems)} problems", *problems[:10], sep="\n  ")
            return 1
    print(f"loaded release {release} (SHA256SUMS {package['sums_sha256'][:16]}...)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
