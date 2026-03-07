"""Base contracts and record models for source plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional


RECORD_SOURCE = "source"
RECORD_SKIP = "skip"
RECORD_ERROR = "error"


@dataclass
class SourceRecord:
    """Represents a single source-plugin event for scanner orchestration."""

    record_type: str
    plugin_name: str
    source_type: str
    source_path: str
    text: str = ""
    content_hash: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    precomputed_findings: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""


def source_record(
    *,
    plugin_name: str,
    source_type: str,
    source_path: str,
    text: str,
    content_hash: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    precomputed_findings: Optional[List[Dict[str, Any]]] = None,
) -> SourceRecord:
    return SourceRecord(
        record_type=RECORD_SOURCE,
        plugin_name=plugin_name,
        source_type=source_type,
        source_path=source_path,
        text=text,
        content_hash=content_hash,
        metadata=metadata or {},
        precomputed_findings=precomputed_findings or [],
    )


def skip_record(
    *,
    plugin_name: str,
    source_type: str,
    source_path: str,
    reason: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> SourceRecord:
    return SourceRecord(
        record_type=RECORD_SKIP,
        plugin_name=plugin_name,
        source_type=source_type,
        source_path=source_path,
        metadata=metadata or {},
        reason=reason,
    )


def error_record(
    *,
    plugin_name: str,
    source_type: str,
    source_path: str,
    error_message: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> SourceRecord:
    return SourceRecord(
        record_type=RECORD_ERROR,
        plugin_name=plugin_name,
        source_type=source_type,
        source_path=source_path,
        metadata=metadata or {},
        reason=error_message,
    )


class SourcePlugin(ABC):
    """Contract for scanner source plugins."""

    plugin_name = "base"
    source_type = "generic"

    @abstractmethod
    def iter_records(self) -> Iterator[SourceRecord]:
        """Yield source/skip/error records for scanner consumption."""
