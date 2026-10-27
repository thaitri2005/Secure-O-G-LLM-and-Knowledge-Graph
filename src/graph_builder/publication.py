"""Immutable releases behind an atomically switched pointer (design §4.3, D-24).

A publication root holds ``releases/<release_id>/`` directories and a small ``CURRENT.json`` pointer. A new
bundle is validated while still staged, renamed into ``releases/`` under a fresh ID, and only then made current
by replacing the pointer file with ``os.replace``, which is atomic on one volume. An interruption at any point
leaves the previous release current and complete; there is no moment without a published bundle.

Readers call ``current_release(root)`` once and keep using that path. The previous release is kept, so a reader
that resolved it just before a switch can finish; older ones are pruned.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from typing import Callable

POINTER = "CURRENT.json"
RELEASES = "releases"
RELEASE_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{12}$")


class PublicationError(ValueError):
    pass


def current_release(root: Path) -> Path:
    """The directory readers should use: the pointed-to release, or ``root`` itself for an old flat bundle."""
    pointer = root / POINTER
    if pointer.exists():
        release = json.loads(pointer.read_text(encoding="utf-8"))["release"]
        if not RELEASE_ID.match(release):
            raise PublicationError(f"{pointer}: malformed release ID {release!r}")
        path = root / RELEASES / release
        if not path.is_dir():
            raise PublicationError(f"{pointer} points to a missing release {release}")
        return path
    if (root / "SHA256SUMS").exists():
        return root
    raise FileNotFoundError(f"No published bundle in {root}")


def publish(staging: Path, root: Path, marker: str, digest: str,
            validate: Callable[[Path], list[str]] | None = None) -> Path:
    """Validate ``staging``, move it into ``root/releases`` and switch the pointer. Returns the release path.

    ``marker`` is a file every bundle of this kind has (for example ``summary.json``); a non-empty ``root``
    without a pointer, releases or that marker is refused rather than mixed with unrelated files. ``digest``
    (hex) names the release together with the UTC time. On failure the staging directory is left to the caller.
    """
    if root.exists() and any(root.iterdir()) and not (
            (root / POINTER).exists() or (root / RELEASES).is_dir() or (root / marker).exists()):
        raise PublicationError(f"Refusing to publish into {root}: it is not a bundle directory")
    if validate is not None:
        problems = validate(staging)
        if problems:
            raise PublicationError(f"Staged bundle failed validation ({len(problems)} problems): {problems[:5]}")
    releases = root / RELEASES
    releases.mkdir(parents=True, exist_ok=True)
    release_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{digest[:12]}"
    target = releases / release_id
    if target.exists():
        raise PublicationError(f"Release {release_id} already exists")
    previous = json.loads((root / POINTER).read_text(encoding="utf-8"))["release"] \
        if (root / POINTER).exists() else None
    staging.rename(target)
    _write_pointer(root, {"release": release_id, "previous": previous,
                          "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    _prune(releases, keep={release_id, previous})
    return target


def _write_pointer(root: Path, value: dict) -> None:
    partial = root / f".{POINTER}.partial"
    with partial.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=1) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(partial, root / POINTER)


def _prune(releases: Path, keep: set[str | None]) -> None:
    """Remove releases other than the current and previous ones. Failures only leave extra directories."""
    for path in releases.iterdir():
        if path.is_dir() and RELEASE_ID.match(path.name) and path.name not in keep:
            shutil.rmtree(path, ignore_errors=True)
