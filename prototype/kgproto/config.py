"""Prototype connection settings. Credentials are throwaway values for localhost-only containers."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = ROOT / "prototype"
# The ontology is an input file (design §6, D-29); KG_PROFILE selects another one without code changes.
PROFILE_PATH = Path(os.environ.get("KG_PROFILE", PROTOTYPE / "profiles/oil_wells.json"))
RESULTS = PROTOTYPE / "results"
BSEE_BUNDLE = ROOT / "data/processed/local/bsee_wells"
BSEE_GRAPH = ROOT / "data/processed/local/bsee_graph"
PDF_BUNDLE = ROOT / "data/processed"
REPORT_DOC = "gdr882_ak3_eowr"

NEO4J_URI = "bolt://127.0.0.1:7687"
NEO4J_AUTH = ("neo4j", "prototype-only")
POSTGRES_DSN = "host=127.0.0.1 port=5433 dbname=kg user=kg password=prototype-only"
LLAMA_URL = "http://127.0.0.1:8080"
MODEL = "qwen2.5-3b-instruct-q4_k_m.gguf (SHA256 626b4a66…5c62d)"
