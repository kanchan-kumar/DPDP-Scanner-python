#!/usr/bin/env python3
"""Backward-compatible wrapper around the new modular main entrypoint."""

from __future__ import annotations

from main import main


if __name__ == "__main__":
    raise SystemExit(main())

