"""Compatibility shim for the package no-thinking gateway."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from kgbuilder.runtime.gateway import MIN_TOKENS, PASS_THROUGH, STOP, render, start, summarize
