"""Common utility functions used across scanner modules."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    """Return current UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hash of a file for traceability in reports."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

