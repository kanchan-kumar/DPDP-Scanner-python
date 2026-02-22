"""File discovery and filtering logic for scan candidate selection."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Iterable, Iterator, Sequence


def allowed_extension(path: Path, include_extensions: Iterable[str]) -> bool:
    """Return True when file extension is included or extension filtering is disabled."""
    allowed = {ext.lower() for ext in include_extensions}
    if not allowed:
        return True
    return path.suffix.lower() in allowed


def is_excluded_file(path: Path, exclude_globs: Iterable[str]) -> bool:
    """Return True when file name/path matches a configured exclusion glob."""
    path_str = str(path)
    for pattern in exclude_globs:
        if fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(path_str, pattern):
            return True
    return False


def iter_candidate_files(
    input_paths: Sequence[str],
    recursive: bool,
    include_extensions: Iterable[str],
    exclude_dirs: Iterable[str],
    exclude_globs: Iterable[str],
) -> Iterator[Path]:
    """Yield files that satisfy include/exclude scanning criteria."""
    excluded_dir_names = set(exclude_dirs)

    for raw_path in input_paths:
        candidate = Path(raw_path).expanduser()
        if not candidate.exists():
            continue

        if candidate.is_file():
            if allowed_extension(candidate, include_extensions) and not is_excluded_file(
                candidate, exclude_globs
            ):
                yield candidate
            continue

        if recursive:
            for root, dir_names, file_names in os.walk(candidate):
                dir_names[:] = [name for name in dir_names if name not in excluded_dir_names]
                root_path = Path(root)
                for filename in file_names:
                    file_path = root_path / filename
                    if not allowed_extension(file_path, include_extensions):
                        continue
                    if is_excluded_file(file_path, exclude_globs):
                        continue
                    yield file_path
        else:
            for child in candidate.iterdir():
                if not child.is_file():
                    continue
                if not allowed_extension(child, include_extensions):
                    continue
                if is_excluded_file(child, exclude_globs):
                    continue
                yield child

