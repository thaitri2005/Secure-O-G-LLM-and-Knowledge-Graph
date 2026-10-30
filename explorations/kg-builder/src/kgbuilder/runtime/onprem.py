"""Loopback-only runtime configuration and socket egress guard."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
from pathlib import Path
from kgbuilder.core.project import PROJECT_ROOT, LOCAL_HOSTS, is_loopback, require_loopback_url
_log_path: Path | None = None
_seen: set[tuple[str, str, bool]] = set()
_opened: set[Path] = set()
_lock = threading.RLock()


def load_env() -> None:
    """Load the project environment, keeping all caches and temporary files local."""
    path = PROJECT_ROOT / "configs" / "runtime" / "onprem.env"
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if value.startswith("./"):
                value = str(PROJECT_ROOT / value[2:])
            if key in {"NO_PROXY", "no_proxy"}:
                os.environ[key] = "*"
            else:
                os.environ.setdefault(key, value)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    temp = Path(os.environ.get("TEMP", str(PROJECT_ROOT / ".cache" / "tmp")))
    temp.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"


def _target(address: object) -> tuple[object, object]:
    if isinstance(address, tuple) and len(address) >= 2:
        return address[0], address[1]
    return address, None


def guard_network(log_path: Path) -> Path:
    """Patch socket operations so non-loopback connects are logged and refused."""
    global _log_path, _seen
    resolved = Path(log_path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved not in _opened:
        resolved.open("w", encoding="utf-8").close()
        _opened.add(resolved)
    _log_path = resolved
    _seen = set()
    if getattr(socket.socket.connect, "_kgb_guard", False):
        return resolved
    real_connect, real_connect_ex, real_getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def record(kind: str, host: object, port: object, allowed: bool) -> None:
        global _seen
        target = f"{host}:{port}"
        key = (kind, target, allowed)
        with _lock:
            if key in _seen:
                return
            _seen.add(key)
            if _log_path is not None:
                with _log_path.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(json.dumps({"kind": kind, "target": target, "allowed": allowed}, separators=(",", ":")) + "\n")

    def check(kind: str, host: object, port: object) -> None:
        allowed = is_loopback(host)
        record(kind, host, port, allowed)
        if not allowed:
            raise ConnectionRefusedError(f"on-prem guard blocked {kind} to {host}:{port}")

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            host, port = _target(address)
            check("connect", host, port)
        return real_connect(self, address)

    def connect_ex(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            host, port = _target(address)
            check("connect", host, port)
        return real_connect_ex(self, address)

    def getaddrinfo(host, port, *args, **kwargs):
        if host is not None:
            check("dns", host.decode() if isinstance(host, bytes) else host, port)
        return real_getaddrinfo(host, port, *args, **kwargs)

    connect._kgb_guard = True
    connect_ex._kgb_guard = True
    getaddrinfo._kgb_guard = True
    socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, getaddrinfo
    return resolved


def blocked_count(log_path: Path) -> int:
    """Count blocked operations in a guard log."""
    if not Path(log_path).exists():
        return 0
    count = 0
    for line in Path(log_path).read_text(encoding="utf-8").splitlines():
        if line.strip() and json.loads(line).get("allowed") is False:
            count += 1
    return count
