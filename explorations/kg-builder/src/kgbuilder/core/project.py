"""Python 3.9-safe project paths and loopback URL validation."""
from __future__ import annotations

import ipaddress
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def is_loopback(host: object) -> bool:
    """Return whether a hostname or address is a loopback destination."""
    if not isinstance(host, str):
        return False
    if host.lower() in LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def require_loopback_url(url: str, key: str, schemes: tuple) -> None:
    """Validate a URL scheme and require a loopback host."""
    parsed = urlparse(url)
    if parsed.scheme not in schemes:
        raise ValueError(f"{key}: scheme '{parsed.scheme}' is not allowed")
    host = parsed.hostname
    if not is_loopback(host):
        raise ValueError(f"{key}: host '{host}' is not loopback")
