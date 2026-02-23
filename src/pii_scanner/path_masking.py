"""File path masking utilities for privacy-preserving output JSON."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List


MASK_MODE_FULL = "full"
MASK_MODE_BASENAME = "basename"
MASK_MODE_RELATIVE = "relative"
MASK_MODE_HASH = "hash"
MASK_MODE_REDACTED = "redacted"


class FilePathMasker:
    """Mask file paths according to output privacy settings."""

    def __init__(
        self,
        enabled: bool,
        mode: str,
        base_dirs: Iterable[Path],
        hash_salt: str,
    ) -> None:
        self.enabled = enabled
        self.mode = (mode or MASK_MODE_FULL).strip().lower()
        self.base_dirs: List[Path] = []
        for base_dir in base_dirs:
            try:
                self.base_dirs.append(base_dir.resolve())
            except Exception:
                continue
        self.hash_salt = hash_salt

    def _as_relative(self, path: Path) -> str:
        resolved = path.resolve()
        for base_dir in self.base_dirs:
            try:
                return str(resolved.relative_to(base_dir))
            except Exception:
                continue
        return path.name

    def _as_hash(self, path: Path) -> str:
        raw = f"{self.hash_salt}|{path.resolve()}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        suffix = path.suffix or ""
        return f"file_{digest}{suffix}"

    def mask(self, path: Path) -> str:
        if not self.enabled or self.mode == MASK_MODE_FULL:
            return str(path)
        if self.mode == MASK_MODE_BASENAME:
            return path.name
        if self.mode == MASK_MODE_RELATIVE:
            return self._as_relative(path)
        if self.mode == MASK_MODE_HASH:
            return self._as_hash(path)
        if self.mode == MASK_MODE_REDACTED:
            return "[REDACTED_PATH]"
        return str(path)


def build_file_path_masker(
    output_cfg: Dict[str, Any],
    scan_cfg: Dict[str, Any],
) -> FilePathMasker:
    enabled = bool(output_cfg.get("mask_file_paths", False))
    mode = str(output_cfg.get("file_path_mask_mode", MASK_MODE_FULL))
    hash_salt = str(output_cfg.get("file_path_hash_salt", ""))

    base_dirs: List[Path] = []
    custom_base_dir = str(output_cfg.get("file_path_base_dir", "")).strip()
    if custom_base_dir:
        base_dirs.append(Path(custom_base_dir).expanduser())
    else:
        for raw_path in scan_cfg.get("input_paths", []) or []:
            candidate = Path(str(raw_path)).expanduser()
            if candidate.exists():
                base_dirs.append(candidate if candidate.is_dir() else candidate.parent)
        if not base_dirs:
            base_dirs.append(Path.cwd())

    return FilePathMasker(
        enabled=enabled,
        mode=mode,
        base_dirs=base_dirs,
        hash_salt=hash_salt,
    )
