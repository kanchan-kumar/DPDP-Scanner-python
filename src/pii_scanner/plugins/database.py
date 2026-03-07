"""Database source plugin implementation using piicatcher."""

from __future__ import annotations

from contextlib import suppress
from typing import Any, Dict, Iterator, List, Optional, Set

from .base import SourcePlugin, SourceRecord, error_record, skip_record, source_record
from .piicatcher_adapter import (
    derive_database_name_from_url,
    derive_source_type_from_connection,
    detect_pii_columns_with_piicatcher,
)

try:
    from sqlalchemy import MetaData, Table, create_engine, select
except Exception:  # pragma: no cover - optional dependency guard
    MetaData = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]
    create_engine = None  # type: ignore[assignment]
    select = None  # type: ignore[assignment]


DEFAULT_SAMPLE_VALUES_CFG: Dict[str, Any] = {
    "enabled": True,
    "limit_per_column": 5,
    "max_value_length": 120,
    "distinct": True,
    "exclude_null": True,
    "exclude_empty_strings": True,
}

RELATIONAL_SAMPLE_SOURCE_TYPES = {
    "sqlite",
    "mysql",
    "postgresql",
    "redshift",
    "mssql",
    "oracle",
    "snowflake",
}


def _as_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        output: List[str] = []
        for item in value:
            text_item = _as_str(item)
            if text_item:
                output.append(text_item)
        return output
    return []


def _normalize_table_name(value: str) -> str:
    return _as_str(value).lower()


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = _as_str(value).lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        candidate = int(value)
    except Exception:
        return default
    return max(minimum, min(maximum, candidate))


def _normalize_sample_values_cfg(raw_cfg: Any) -> Dict[str, Any]:
    normalized = dict(DEFAULT_SAMPLE_VALUES_CFG)
    if isinstance(raw_cfg, bool):
        normalized["enabled"] = raw_cfg
        return normalized
    if not isinstance(raw_cfg, dict):
        return normalized

    normalized["enabled"] = _as_bool(raw_cfg.get("enabled"), normalized["enabled"])
    normalized["limit_per_column"] = _as_int(
        raw_cfg.get("limit_per_column", raw_cfg.get("limit", normalized["limit_per_column"])),
        normalized["limit_per_column"],
        minimum=1,
        maximum=1000,
    )
    normalized["max_value_length"] = _as_int(
        raw_cfg.get("max_value_length", raw_cfg.get("max_chars", normalized["max_value_length"])),
        normalized["max_value_length"],
        minimum=8,
        maximum=10000,
    )
    normalized["distinct"] = _as_bool(raw_cfg.get("distinct"), normalized["distinct"])
    normalized["exclude_null"] = _as_bool(raw_cfg.get("exclude_null"), normalized["exclude_null"])
    normalized["exclude_empty_strings"] = _as_bool(
        raw_cfg.get("exclude_empty_strings"),
        normalized["exclude_empty_strings"],
    )
    return normalized


def _format_sample_value(value: Any, max_chars: int) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            text = value.decode("utf-8", errors="replace")
        except Exception:
            text = value.hex()
    else:
        text = str(value)
    text = text.strip()
    if max_chars > 0 and len(text) > max_chars:
        return f"{text[:max_chars]}..."
    return text


def _table_selection_sets(connection_cfg: Dict[str, Any]) -> tuple[Set[str], Set[str]]:
    include_tables: Set[str] = set()
    exclude_tables: Set[str] = set()

    for item in connection_cfg.get("tables", []) or []:
        if isinstance(item, str):
            normalized = _normalize_table_name(item)
            if normalized:
                include_tables.add(normalized)
        elif isinstance(item, dict):
            name = _normalize_table_name(item.get("name", ""))
            if name:
                include_tables.add(name)

    for item in _as_str_list(connection_cfg.get("include_tables", [])):
        normalized = _normalize_table_name(item)
        if normalized:
            include_tables.add(normalized)

    for item in _as_str_list(connection_cfg.get("exclude_tables", [])):
        normalized = _normalize_table_name(item)
        if normalized:
            exclude_tables.add(normalized)

    return include_tables, exclude_tables


def _parse_table_key(table_key: str) -> tuple[str, str]:
    normalized = _as_str(table_key)
    if "." not in normalized:
        return "", normalized
    schema_name, table_name = normalized.rsplit(".", 1)
    return schema_name, table_name


def _metadata_without_findings(metadata: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(metadata)
    cleaned.pop("precomputed_findings", None)
    return cleaned


def _connection_endpoint(connection_cfg: Dict[str, Any], url: str) -> str:
    endpoint = _as_str(connection_cfg.get("host") or "")
    if endpoint:
        return endpoint
    url_text = _as_str(url)
    if "@" in url_text:
        return url_text.split("@", 1)[1]
    return url_text


class _ColumnSampleCollector:
    """Fetch sample values for detected PII columns from a live DB connection."""

    def __init__(
        self,
        *,
        connection_url: str,
        connection_type: str,
        sample_cfg: Dict[str, Any],
    ) -> None:
        self.connection_url = connection_url
        self.connection_type = _normalize_table_name(connection_type)
        self.sample_cfg = sample_cfg
        self.enabled = bool(sample_cfg.get("enabled", False))
        self.limit_per_column = int(sample_cfg.get("limit_per_column", 5))
        self.max_value_length = int(sample_cfg.get("max_value_length", 120))
        self.distinct = bool(sample_cfg.get("distinct", True))
        self.exclude_null = bool(sample_cfg.get("exclude_null", True))
        self.exclude_empty_strings = bool(sample_cfg.get("exclude_empty_strings", True))
        self._engine: Any = None
        self._connection: Any = None
        self._table_cache: Dict[tuple[str, str], Any] = {}
        self._init_error: Optional[str] = None

    def __enter__(self) -> "_ColumnSampleCollector":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._connection is not None:
            with suppress(Exception):
                self._connection.close()
            self._connection = None
        if self._engine is not None:
            with suppress(Exception):
                self._engine.dispose()
            self._engine = None

    def _ensure_connection(self) -> Optional[str]:
        if not self.enabled:
            return None
        if self._init_error:
            return self._init_error
        if self._connection is not None:
            return None
        if self.connection_type not in RELATIONAL_SAMPLE_SOURCE_TYPES:
            self._init_error = (
                f"sample value extraction is not supported for source type '{self.connection_type}'."
            )
            return self._init_error
        if create_engine is None or MetaData is None or Table is None or select is None:
            self._init_error = "sqlalchemy is not available for sample value extraction."
            return self._init_error
        try:
            self._engine = create_engine(self.connection_url)
            self._connection = self._engine.connect()
        except Exception as exc:
            self._init_error = (
                "unable to open database connection for sample values "
                f"({exc.__class__.__name__})."
            )
            return self._init_error
        return None

    def _resolve_table(self, schema_name: str, table_name: str) -> tuple[Optional[Any], Optional[str]]:
        schema_key = _normalize_table_name(schema_name)
        table_key = _normalize_table_name(table_name)
        cache_key = (schema_key, table_key)
        if cache_key in self._table_cache:
            return self._table_cache[cache_key], None

        connection_error = self._ensure_connection()
        if connection_error:
            return None, connection_error

        metadata = MetaData()  # type: ignore[operator]
        kwargs: Dict[str, Any] = {
            "autoload": True,
            "autoload_with": self._connection,
        }
        if schema_name:
            kwargs["schema"] = schema_name

        try:
            table_obj = Table(table_name, metadata, **kwargs)  # type: ignore[misc]
        except Exception as exc:
            return None, (
                f"unable to load table metadata for '{schema_name + '.' if schema_name else ''}"
                f"{table_name}' ({exc.__class__.__name__})."
            )

        self._table_cache[cache_key] = table_obj
        return table_obj, None

    @staticmethod
    def _resolve_column(table_obj: Any, column_name: str) -> Optional[Any]:
        direct = table_obj.columns.get(column_name)
        if direct is not None:
            return direct
        normalized = _normalize_table_name(column_name)
        for existing in table_obj.columns:
            if _normalize_table_name(existing.name) == normalized:
                return existing
        return None

    def sample_values(
        self,
        *,
        schema_name: str,
        table_name: str,
        column_name: str,
    ) -> tuple[List[str], Optional[str]]:
        if not self.enabled:
            return [], None

        table_obj, table_error = self._resolve_table(schema_name, table_name)
        if table_error:
            return [], table_error
        if table_obj is None:
            return [], "unable to resolve table metadata for sample extraction."

        column_obj = self._resolve_column(table_obj, column_name)
        if column_obj is None:
            return [], (
                f"column '{column_name}' not found while extracting sample values."
            )

        stmt = select([column_obj])  # type: ignore[misc]
        if self.exclude_null:
            stmt = stmt.where(column_obj != None)  # noqa: E711
        if self.distinct:
            stmt = stmt.distinct()
        if self.limit_per_column > 0:
            stmt = stmt.limit(self.limit_per_column)

        try:
            rows = self._connection.execute(stmt).fetchall()
        except Exception as exc:
            return [], (
                "unable to read sample values "
                f"for '{schema_name + '.' if schema_name else ''}{table_name}.{column_name}' "
                f"({exc.__class__.__name__})."
            )

        sample_values: List[str] = []
        for row in rows:
            raw_value = row[0] if row is not None else None
            if raw_value is None and self.exclude_null:
                continue
            text_value = _format_sample_value(raw_value, self.max_value_length)
            if self.exclude_empty_strings and text_value == "":
                continue
            sample_values.append(text_value)
        return sample_values, None


class DatabaseSourcePlugin(SourcePlugin):
    """Scan local/remote databases and emit piicatcher findings."""

    plugin_name = "database"
    source_type = "database"

    def __init__(self, database_cfg: Dict[str, Any], output_cfg: Dict[str, Any]) -> None:
        self.database_cfg = database_cfg
        self.output_cfg = output_cfg
        self.connections = database_cfg.get("connections", []) or []
        self.global_piicatcher_cfg = database_cfg.get("piicatcher", {}) or {}
        self.global_sample_values_cfg = _normalize_sample_values_cfg(
            database_cfg.get("sample_values", {})
        )

    def _resolve_piicatcher_cfg(self, connection_cfg: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(self.global_piicatcher_cfg)
        merged.update(connection_cfg.get("piicatcher", {}) or {})
        if "enabled" not in merged:
            merged["enabled"] = True
        return merged

    def _resolve_sample_values_cfg(self, connection_cfg: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(self.global_sample_values_cfg)
        connection_cfg_value = connection_cfg.get("sample_values", {})
        if isinstance(connection_cfg_value, bool):
            merged["enabled"] = connection_cfg_value
        elif isinstance(connection_cfg_value, dict):
            merged.update(connection_cfg_value)
        return _normalize_sample_values_cfg(merged)

    def iter_records(self) -> Iterator[SourceRecord]:
        if not isinstance(self.connections, list) or not self.connections:
            yield skip_record(
                plugin_name=self.plugin_name,
                source_type=self.source_type,
                source_path="db://",
                reason="Database plugin enabled but no connections configured.",
            )
            return

        enabled_connection_found = False
        for index, connection_cfg in enumerate(self.connections, start=1):
            if not isinstance(connection_cfg, dict):
                continue
            if not bool(connection_cfg.get("enabled", True)):
                continue
            enabled_connection_found = True

            connection_name = _as_str(connection_cfg.get("name") or f"database_{index}")
            if not connection_name:
                connection_name = f"database_{index}"

            url = _as_str(
                connection_cfg.get("url")
                or connection_cfg.get("uri")
                or connection_cfg.get("connection_string")
                or connection_cfg.get("dsn")
                or ""
            )
            if not url:
                yield error_record(
                    plugin_name=self.plugin_name,
                    source_type=self.source_type,
                    source_path=f"db://{connection_name}",
                    error_message="Missing connection URL (url/uri/connection_string/dsn).",
                )
                continue

            piicatcher_cfg = self._resolve_piicatcher_cfg(connection_cfg)
            if not bool(piicatcher_cfg.get("enabled", True)):
                yield skip_record(
                    plugin_name=self.plugin_name,
                    source_type=self.source_type,
                    source_path=f"db://{connection_name}",
                    reason="piicatcher is disabled for this connection.",
                )
                continue

            (
                columns_by_table,
                piicatcher_metadata,
                piicatcher_error,
            ) = detect_pii_columns_with_piicatcher(
                connection_name=connection_name,
                connection_url=url,
                connection_cfg=connection_cfg,
                piicatcher_cfg=piicatcher_cfg,
            )
            if piicatcher_error:
                yield error_record(
                    plugin_name=self.plugin_name,
                    source_type=self.source_type,
                    source_path=f"db://{connection_name}",
                    error_message=piicatcher_error,
                )
                continue

            include_tables, exclude_tables = _table_selection_sets(connection_cfg)
            connection_type = derive_source_type_from_connection(
                connection_url=url,
                connection_cfg=connection_cfg,
            )
            emitted_records = 0
            sample_values_cfg = self._resolve_sample_values_cfg(connection_cfg)
            with _ColumnSampleCollector(
                connection_url=url,
                connection_type=connection_type,
                sample_cfg=sample_values_cfg,
            ) as sample_collector:
                for table_key, columns in columns_by_table.items():
                    schema_name, table_name = _parse_table_key(table_key)
                    table_token = _normalize_table_name(table_name)
                    schema_table_token = (
                        _normalize_table_name(f"{schema_name}.{table_name}")
                        if schema_name
                        else table_token
                    )

                    if include_tables and table_token not in include_tables and schema_table_token not in include_tables:
                        continue
                    if table_token in exclude_tables or schema_table_token in exclude_tables:
                        continue

                    for column_name, pii_types in columns.items():
                        clean_column = _as_str(column_name)
                        if not clean_column:
                            continue
                        clean_pii_types = [
                            _as_str(pii_type)
                            for pii_type in (pii_types or [])
                            if _as_str(pii_type)
                        ]
                        if not clean_pii_types:
                            clean_pii_types = ["PII"]

                        table_label = f"{schema_name}.{table_name}" if schema_name else table_name
                        source_path = (
                            f"db://{connection_name}/table:{table_label}/column:{clean_column}"
                        )
                        database_name = _as_str(
                            connection_cfg.get("database")
                            or derive_database_name_from_url(url)
                        )
                        source_metadata: Dict[str, Any] = {
                            "connection": connection_name,
                            "connection_type": connection_type,
                            "connection_endpoint": _connection_endpoint(connection_cfg, url),
                            "database": database_name,
                            "schema": schema_name,
                            "table": table_name,
                            "column": clean_column,
                            "pii_types": clean_pii_types,
                            "detector": "piicatcher",
                            "piicatcher_run": {
                                "source_name": piicatcher_metadata.get("source_name", ""),
                                "source_type": piicatcher_metadata.get("source_type", ""),
                                "table_count": piicatcher_metadata.get("table_count", 0),
                                "pii_column_count": piicatcher_metadata.get("pii_column_count", 0),
                            },
                        }

                        if bool(sample_values_cfg.get("enabled", False)):
                            sample_values, sample_error = sample_collector.sample_values(
                                schema_name=schema_name,
                                table_name=table_name,
                                column_name=clean_column,
                            )
                            source_metadata["sample_values"] = sample_values
                            source_metadata["sample_values_count"] = len(sample_values)
                            source_metadata["sample_values_limit"] = int(
                                sample_values_cfg.get("limit_per_column", 5)
                            )
                            if sample_values:
                                source_metadata["sample_value_preview"] = sample_values[0]
                            if sample_error:
                                source_metadata["sample_values_error"] = sample_error

                        logical_text = f"{table_label}.{clean_column}"
                        findings: List[Dict[str, Any]] = []
                        for pii_type in clean_pii_types:
                            findings.append(
                                {
                                    "entity_type": pii_type,
                                    "category": "PERSONAL",
                                    "score": 1.0,
                                    "text": logical_text,
                                    "start": 0,
                                    "end": len(logical_text),
                                    "file_path": source_path,
                                    "source_type": self.source_type,
                                    "source_plugin": self.plugin_name,
                                    "source_metadata": source_metadata,
                                    "recognizer_name": "piicatcher",
                                }
                            )

                        yield source_record(
                            plugin_name=self.plugin_name,
                            source_type=self.source_type,
                            source_path=source_path,
                            text="",
                            content_hash=None,
                            metadata=_metadata_without_findings(source_metadata),
                            precomputed_findings=findings,
                        )
                        emitted_records += 1

            if emitted_records == 0:
                yield skip_record(
                    plugin_name=self.plugin_name,
                    source_type=self.source_type,
                    source_path=f"db://{connection_name}",
                    reason="No pii columns detected by piicatcher.",
                    metadata={
                        "connection": connection_name,
                        "database": _as_str(
                            connection_cfg.get("database")
                            or derive_database_name_from_url(url)
                        ),
                        "detector": "piicatcher",
                    },
                )

            if connection_cfg.get("queries"):
                yield skip_record(
                    plugin_name=self.plugin_name,
                    source_type=self.source_type,
                    source_path=f"db://{connection_name}/queries",
                    reason=(
                        "piicatcher table scanning is enabled; "
                        "custom SQL query scanning is not supported in piicatcher-only mode."
                    ),
                )

        if not enabled_connection_found:
            yield skip_record(
                plugin_name=self.plugin_name,
                source_type=self.source_type,
                source_path="db://",
                reason="No enabled database connections configured.",
            )
