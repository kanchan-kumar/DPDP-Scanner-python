#!/usr/bin/env python3
"""Application starter; wires project root execution to modular src package."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Optional, Sequence

MIN_SUPPORTED_PYTHON = (3, 10)
MAX_SUPPORTED_PYTHON_EXCLUSIVE = (3, 14)


def _ensure_src_on_path() -> None:
    """Ensure src/ is importable when running from repository root or bundled app."""
    root = Path(__file__).resolve().parent
    src_path = root / "src"
    src_str = str(src_path)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


def _is_supported_python() -> bool:
    """Allow only Python versions tested with the scanner dependency stack."""
    current = (sys.version_info.major, sys.version_info.minor)
    return MIN_SUPPORTED_PYTHON <= current < MAX_SUPPORTED_PYTHON_EXCLUSIVE


def _python_series() -> str:
    return (
        f"{MIN_SUPPORTED_PYTHON[0]}.{MIN_SUPPORTED_PYTHON[1]}-"
        f"{MAX_SUPPORTED_PYTHON_EXCLUSIVE[0]}.{MAX_SUPPORTED_PYTHON_EXCLUSIVE[1] - 1}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Invoke scanner CLI main function."""
    if not _is_supported_python():
        current = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        print(
            f"Unsupported Python runtime: {current}. "
            f"Use Python {_python_series()} for this project.",
            file=sys.stderr,
        )
        return 1

    _ensure_src_on_path()
    warnings.filterwarnings(
        "ignore",
        message="urllib3 v2 only supports OpenSSL 1.1.1+.*",
    )
    from pii_scanner.cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
