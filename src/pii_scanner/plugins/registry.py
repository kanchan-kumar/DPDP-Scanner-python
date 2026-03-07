"""Registry and factory helpers for source plugins."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from .base import SourcePlugin
from .database import DatabaseSourcePlugin
from .filesystem import FilesystemSourcePlugin


def _source_enabled(
    source_name: str,
    source_cfg: Dict[str, Any],
    enabled_source_names: List[str],
    default_enabled: bool,
) -> bool:
    source_settings = source_cfg.get(source_name, {}) or {}
    enabled_flag = source_settings.get("enabled")
    if enabled_flag is None:
        enabled_flag = default_enabled
    if not bool(enabled_flag):
        return False
    if not enabled_source_names:
        return True
    return source_name in enabled_source_names


def create_source_plugins(
    config: Dict[str, Any],
    output_path: Path,
    logger: logging.Logger,
) -> List[SourcePlugin]:
    """Build enabled source plugins for the current scan run."""
    source_cfg = config.get("sources", {}) or {}
    enabled_source_names = [
        str(name).strip()
        for name in (source_cfg.get("enabled_sources", []) or [])
        if str(name).strip()
    ]

    scan_cfg = config.get("scan", {}) or {}
    output_cfg = config.get("output", {}) or {}
    filesystem_cfg = source_cfg.get("filesystem", {}) or {}
    database_cfg = source_cfg.get("database", {}) or {}

    plugins: List[SourcePlugin] = []
    if _source_enabled(
        source_name="filesystem",
        source_cfg=source_cfg,
        enabled_source_names=enabled_source_names,
        default_enabled=True,
    ):
        plugins.append(
            FilesystemSourcePlugin(
                scan_cfg=scan_cfg,
                filesystem_cfg=filesystem_cfg,
                output_cfg=output_cfg,
                output_path=output_path,
            )
        )

    if _source_enabled(
        source_name="database",
        source_cfg=source_cfg,
        enabled_source_names=enabled_source_names,
        default_enabled=False,
    ):
        plugins.append(
            DatabaseSourcePlugin(
                database_cfg=database_cfg,
                output_cfg=output_cfg,
            )
        )

    if plugins:
        return plugins

    logger.warning(
        "No source plugins enabled by config. Falling back to filesystem source."
    )
    return [
        FilesystemSourcePlugin(
            scan_cfg=scan_cfg,
            filesystem_cfg=filesystem_cfg,
            output_cfg=output_cfg,
            output_path=output_path,
        )
    ]
