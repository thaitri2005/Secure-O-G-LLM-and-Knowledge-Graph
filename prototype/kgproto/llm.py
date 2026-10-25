"""Call the local llama.cpp server with JSON-schema-constrained output."""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .config import LLAMA_URL


def structured(system: str, user: str, schema: dict[str, Any], max_tokens: int = 1200) -> tuple[Any, int]:
    """Return the parsed JSON (or None if the output was unusable) and the latency in milliseconds."""
    started = time.perf_counter()
    response = httpx.post(f"{LLAMA_URL}/v1/chat/completions", timeout=600, json={
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0, "max_tokens": max_tokens, "cache_prompt": True,
        "response_format": {"type": "json_schema", "json_schema": {"name": "output", "schema": schema}}})
    response.raise_for_status()
    elapsed = int((time.perf_counter() - started) * 1000)
    try:
        return json.loads(response.json()["choices"][0]["message"]["content"]), elapsed
    except (KeyError, json.JSONDecodeError):
        return None, elapsed
