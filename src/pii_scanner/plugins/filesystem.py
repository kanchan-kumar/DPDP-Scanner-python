"""Filesystem source plugin implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator, List

from ..discovery import iter_candidate_files
from ..extractors import extract_text
from ..path_masking import build_file_path_masker
from ..utils import sha256_file
from .base import SourcePlugin, SourceRecord, error_record, skip_record, source_record


class FilesystemSourcePlugin(SourcePlugin):
    """Scan local filesystem files and yield text records for analysis."""

    plugin_name = "filesystem"
    source_type = "filesystem"

    def __init__(
        self,
        scan_cfg: Dict[str, Any],
        filesystem_cfg: Dict[str, Any],
        output_cfg: Dict[str, Any],
        output_path: Path,
    ) -> None:
        self.scan_cfg = scan_cfg
        self.filesystem_cfg = filesystem_cfg
        self.output_cfg = output_cfg
        self.output_path = output_path.resolve()
        self.file_path_masker = build_file_path_masker(output_cfg, scan_cfg)
        self.locations = self._load_locations()

    @staticmethod
    def _as_str_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            cleaned = value.strip()
            return [cleaned] if cleaned else []
        if isinstance(value, list):
            output: List[str] = []
            for item in value:
                cleaned = str(item).strip()
                if cleaned:
                    output.append(cleaned)
            return output
        return []

    def _load_locations(self) -> List[Dict[str, Any]]:
        raw_locations = self.filesystem_cfg.get("locations", [])
        if not isinstance(raw_locations, list):
            raw_locations = []

        locations: List[Dict[str, Any]] = []
        for index, location in enumerate(raw_locations, start=1):
            if not isinstance(location, dict):
                continue
            normalized = dict(location)
            normalized["name"] = str(normalized.get("name") or f"filesystem_{index}")
            normalized["enabled"] = bool(normalized.get("enabled", True))
            normalized["provider"] = (
                str(normalized.get("provider") or "local").strip().lower() or "local"
            )
            locations.append(normalized)

        if locations:
            return locations

        return [
            {
                "name": "local_filesystem",
                "enabled": True,
                "provider": "local",
            }
        ]

    def _location_scan_cfg(self, location: Dict[str, Any]) -> Dict[str, Any]:
        resolved = dict(self.scan_cfg)
        for key in [
            "input_paths",
            "recursive",
            "include_extensions",
            "exclude_dirs",
            "exclude_file_globs",
            "max_file_size_mb",
            "read_binary_files_as_text",
            "pdf_max_pages",
            "ocr_images",
        ]:
            if key in location:
                resolved[key] = location[key]
        return resolved

    def _iter_local_paths(self, location_scan_cfg: Dict[str, Any]) -> Iterator[Path]:
        paths = self._as_str_list(location_scan_cfg.get("input_paths")) or ["."]
        include_extensions = self._as_str_list(location_scan_cfg.get("include_extensions"))
        exclude_dirs = self._as_str_list(location_scan_cfg.get("exclude_dirs"))
        exclude_globs = self._as_str_list(location_scan_cfg.get("exclude_file_globs"))
        recursive = bool(location_scan_cfg.get("recursive", True))

        yield from iter_candidate_files(
            input_paths=paths,
            recursive=recursive,
            include_extensions=include_extensions,
            exclude_dirs=exclude_dirs,
            exclude_globs=exclude_globs,
        )

    def iter_records(self) -> Iterator[SourceRecord]:
        include_hash = bool(self.output_cfg.get("include_file_hash", True))
        location_emitted = False
        location_enabled = False

        for location in self.locations:
            if not bool(location.get("enabled", True)):
                continue
            location_enabled = True
            provider = str(location.get("provider") or "local").lower()
            location_name = str(location.get("name") or "filesystem")
            location_scan_cfg = self._location_scan_cfg(location)
            max_size_bytes = int(location_scan_cfg.get("max_file_size_mb", 20) * 1024 * 1024)

            if provider != "local":
                yield skip_record(
                    plugin_name=self.plugin_name,
                    source_type=self.source_type,
                    source_path=f"filesystem://{location_name}",
                    reason=(
                        f"Unsupported filesystem provider '{provider}'. "
                        "Only provider=local is currently supported."
                    ),
                    metadata={"location": location_name, "provider": provider},
                )
                location_emitted = True
                continue

            for file_path in self._iter_local_paths(location_scan_cfg):
                location_emitted = True
                masked_path = self.file_path_masker.mask(file_path)
                metadata: Dict[str, Any] = {
                    "extension": file_path.suffix.lower(),
                    "provider": provider,
                    "location": location_name,
                }

                try:
                    resolved = file_path.resolve()
                    if resolved == self.output_path:
                        continue

                    file_size = file_path.stat().st_size
                    metadata["file_size_bytes"] = file_size
                except Exception as exc:
                    yield error_record(
                        plugin_name=self.plugin_name,
                        source_type=self.source_type,
                        source_path=masked_path,
                        error_message=str(exc),
                        metadata=metadata,
                    )
                    continue

                if file_size > max_size_bytes:
                    yield skip_record(
                        plugin_name=self.plugin_name,
                        source_type=self.source_type,
                        source_path=masked_path,
                        reason=(
                            "File larger than max_file_size_mb "
                            f"({location_scan_cfg.get('max_file_size_mb')})"
                        ),
                        metadata=metadata,
                    )
                    continue

                try:
                    text = extract_text(file_path, location_scan_cfg)
                except Exception as exc:
                    yield error_record(
                        plugin_name=self.plugin_name,
                        source_type=self.source_type,
                        source_path=masked_path,
                        error_message=str(exc),
                        metadata=metadata,
                    )
                    continue

                content_hash = sha256_file(file_path) if include_hash else None
                yield source_record(
                    plugin_name=self.plugin_name,
                    source_type=self.source_type,
                    source_path=masked_path,
                    text=text,
                    content_hash=content_hash,
                    metadata=metadata,
                )

        if not location_enabled:
            yield skip_record(
                plugin_name=self.plugin_name,
                source_type=self.source_type,
                source_path="filesystem://",
                reason="No enabled filesystem locations configured.",
            )
        elif not location_emitted:
            yield skip_record(
                plugin_name=self.plugin_name,
                source_type=self.source_type,
                source_path="filesystem://",
                reason="Filesystem locations are enabled but no files matched configured filters.",
            )
