"""Helpers for piicatcher-based database PII column discovery."""

from __future__ import annotations

import inspect as pyinspect
import os
import sys
import types
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse


DBCAT_DOC_SUPPORTED_SOURCE_TYPES = [
    "sqlite",
    "mysql",
    "postgresql",
    "redshift",
    "snowflake",
    "athena",
    "bigquery",
]

SOURCE_TYPE_ALIASES = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "pgsql": "postgresql",
    "mariadb": "mysql",
    "mysql": "mysql",
    "sqlserver": "mssql",
    "mssql": "mssql",
    "oracle": "oracle",
    "rds_mysql": "mysql",
    "rds_postgresql": "postgresql",
    "rds_postgres": "postgresql",
    "dynamodb": "dynamodb",
    "aws_dynamodb": "dynamodb",
    "sqlite3": "sqlite",
}

_OPENSSL_X509_FLAG_FALLBACKS = [
    "X509_V_FLAG_CRL_CHECK",
    "X509_V_FLAG_CRL_CHECK_ALL",
    "X509_V_FLAG_IGNORE_CRITICAL",
    "X509_V_FLAG_X509_STRICT",
    "X509_V_FLAG_ALLOW_PROXY_CERTS",
    "X509_V_FLAG_POLICY_CHECK",
    "X509_V_FLAG_EXPLICIT_POLICY",
    "X509_V_FLAG_INHIBIT_MAP",
    "X509_V_FLAG_NOTIFY_POLICY",
    "X509_V_FLAG_CHECK_SS_SIGNATURE",
]


def _apply_pyopenssl_compat_shim() -> None:
    """
    Patch missing OpenSSL verification flags on cryptography's lib module.

    Older pyOpenSSL versions reference these symbols during import, but some
    newer cryptography/OpenSSL builds do not expose every flag. Setting missing
    values to 0 allows imports to proceed for dbcat/piicatcher code paths which
    do not depend on these specific verification flags.
    """
    try:
        from cryptography.hazmat.bindings.openssl.binding import Binding
    except Exception:
        return

    try:
        lib = Binding().lib
    except Exception:
        return

    for flag_name in _OPENSSL_X509_FLAG_FALLBACKS:
        if hasattr(lib, flag_name):
            continue
        try:
            setattr(lib, flag_name, 0)
        except Exception:
            continue


def _install_snowflake_sqlalchemy_stub(source_type: str) -> None:
    """
    Install a lightweight `snowflake.sqlalchemy` stub for non-snowflake scans.

    dbcat imports `snowflake.sqlalchemy.URL` at module import time even when
    scanning MySQL/PostgreSQL. In constrained environments this may pull in a
    snowflake connector stack that is incompatible with the active OpenSSL/
    cryptography versions and fail before scanning begins.
    """
    if _normalize_source_type(source_type) == "snowflake":
        return

    if "snowflake.sqlalchemy" in sys.modules:
        return

    snowflake_module = sys.modules.get("snowflake")
    if snowflake_module is None:
        snowflake_module = types.ModuleType("snowflake")
        snowflake_module.__path__ = []  # type: ignore[attr-defined]
        sys.modules["snowflake"] = snowflake_module

    sqlalchemy_module = types.ModuleType("snowflake.sqlalchemy")

    def _stub_url(**kwargs: Any) -> str:
        account = _as_str(kwargs.get("account"))
        database = _as_str(kwargs.get("database"))
        if account or database:
            return f"snowflake://{account}/{database}"
        return "snowflake://"

    sqlalchemy_module.URL = _stub_url  # type: ignore[attr-defined]
    setattr(snowflake_module, "sqlalchemy", sqlalchemy_module)
    sys.modules["snowflake.sqlalchemy"] = sqlalchemy_module


def _install_goog_stats_stub() -> None:
    """Install a no-op `goog_stats.Stats` to avoid telemetry filesystem writes."""

    class _NoopStats:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            return

        def record_event(self, *_args: Any, **_kwargs: Any) -> str:
            return "collection disabled"

        @classmethod
        def reset(cls) -> None:
            return

    existing = sys.modules.get("goog_stats")
    if existing is not None:
        setattr(existing, "Stats", _NoopStats)
        return

    stub = types.ModuleType("goog_stats")
    stub.Stats = _NoopStats  # type: ignore[attr-defined]
    sys.modules["goog_stats"] = stub


def _as_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in (override or {}).items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _default_source_function_candidates(source_type: str) -> List[str]:
    normalized = source_type.lower()
    mapping = {
        "sqlite": ["add_sqlite_source"],
        "postgresql": ["add_postgresql_source", "add_postgres_source"],
        "postgres": ["add_postgresql_source", "add_postgres_source"],
        "mysql": ["add_mysql_source"],
        "mariadb": ["add_mysql_source", "add_mariadb_source"],
        "mssql": ["add_mssql_source", "add_sqlserver_source"],
        "oracle": ["add_oracle_source"],
        "dynamodb": ["add_dynamodb_source"],
        "redshift": ["add_redshift_source"],
        "snowflake": ["add_snowflake_source"],
        "bigquery": ["add_bigquery_source"],
        "athena": ["add_athena_source"],
    }
    return mapping.get(normalized, [f"add_{normalized}_source"])


def derive_database_name_from_url(connection_url: str) -> str:
    parsed = urlparse(connection_url)
    path = _as_str(parsed.path).lstrip("/")
    return path


def _normalize_source_type(source_type: str) -> str:
    normalized = _as_str(source_type).lower()
    if not normalized:
        return ""
    return SOURCE_TYPE_ALIASES.get(normalized, normalized)


def derive_source_type_from_connection(
    connection_url: str,
    connection_cfg: Dict[str, Any],
) -> str:
    explicit = _as_str(connection_cfg.get("type") or connection_cfg.get("source_type"))
    if explicit:
        normalized_explicit = _normalize_source_type(explicit)
        if normalized_explicit == "rds":
            engine = _as_str(connection_cfg.get("engine") or connection_cfg.get("rds_engine"))
            if engine:
                return _normalize_source_type(engine)
            parsed = urlparse(connection_url)
            return _normalize_source_type(_as_str(parsed.scheme).split("+")[0])
        return normalized_explicit

    parsed = urlparse(connection_url)
    scheme = _as_str(parsed.scheme).lower()
    if not scheme:
        return ""
    return _normalize_source_type(scheme.split("+")[0])


def _resolve_from_env(env_name: str) -> str:
    env_key = _as_str(env_name)
    if not env_key:
        return ""
    return _as_str(os.environ.get(env_key))


def _resolve_password(auth_cfg: Dict[str, Any], parsed: Any) -> str:
    password_env = _as_str(auth_cfg.get("password_env") or auth_cfg.get("password_env_var"))
    if password_env:
        env_value = _resolve_from_env(password_env)
        if env_value:
            return env_value
    return _as_str(auth_cfg.get("password") or parsed.password)


def _derive_source_kwargs(
    source_type: str,
    connection_url: str,
    connection_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    parsed = urlparse(connection_url)
    normalized = _normalize_source_type(source_type)
    auth_cfg = connection_cfg.get("auth", {}) or {}

    if normalized == "sqlite":
        if connection_url.startswith("sqlite:///"):
            path = connection_url[len("sqlite:///") :]
            if not path.startswith("/"):
                path = f"./{path}"
            return {"path": path}
        return {"path": _as_str(parsed.path)}

    kwargs: Dict[str, Any] = {
        "uri": _as_str(connection_cfg.get("host") or parsed.hostname),
        "username": _as_str(auth_cfg.get("username") or parsed.username),
        "password": _resolve_password(auth_cfg, parsed),
        "database": _as_str(
            connection_cfg.get("database")
            or auth_cfg.get("database")
            or _as_str(parsed.path).lstrip("/")
        ),
    }
    if connection_cfg.get("port") is not None:
        kwargs["port"] = int(connection_cfg.get("port"))
    elif parsed.port:
        kwargs["port"] = int(parsed.port)

    if normalized in {"mssql", "oracle"}:
        dsn = _as_str(connection_cfg.get("dsn") or auth_cfg.get("dsn"))
        if dsn:
            kwargs["dsn"] = dsn
        service_name = _as_str(
            connection_cfg.get("service_name") or auth_cfg.get("service_name")
        )
        if service_name:
            kwargs["service_name"] = service_name
        sid = _as_str(connection_cfg.get("sid") or auth_cfg.get("sid"))
        if sid:
            kwargs["sid"] = sid
        driver = _as_str(connection_cfg.get("driver") or auth_cfg.get("driver"))
        if driver:
            kwargs["driver"] = driver

    if normalized == "dynamodb":
        kwargs = {
            "name": _as_str(connection_cfg.get("name") or connection_cfg.get("table_name")),
            "region": _as_str(
                connection_cfg.get("region")
                or auth_cfg.get("region")
                or _resolve_from_env(auth_cfg.get("region_env"))
            ),
            "endpoint_url": _as_str(connection_cfg.get("endpoint_url")),
            "aws_access_key_id": _as_str(
                auth_cfg.get("aws_access_key_id")
                or _resolve_from_env(auth_cfg.get("aws_access_key_id_env"))
            ),
            "aws_secret_access_key": _as_str(
                auth_cfg.get("aws_secret_access_key")
                or _resolve_from_env(auth_cfg.get("aws_secret_access_key_env"))
            ),
            "aws_session_token": _as_str(
                auth_cfg.get("aws_session_token")
                or _resolve_from_env(auth_cfg.get("aws_session_token_env"))
            ),
        }
        kwargs = {key: value for key, value in kwargs.items() if value}
        table_name = _as_str(connection_cfg.get("table_name"))
        if table_name:
            kwargs["table_name"] = table_name

    for key in [
        "keytab_file",
        "kerberos_principal",
        "kerberos_realm",
        "ssl_ca",
        "ssl_cert",
        "ssl_key",
    ]:
        value = _as_str(auth_cfg.get(key) or connection_cfg.get(key))
        if value:
            kwargs[key] = value

    extra_options = connection_cfg.get("extra_options", {}) or {}
    if isinstance(extra_options, dict):
        kwargs = _deep_merge(kwargs, extra_options)

    return kwargs


def _call_with_supported_kwargs(func: Any, kwargs: Dict[str, Any]) -> Any:
    signature = pyinspect.signature(func)
    parameters = signature.parameters
    supports_var_kwargs = any(
        parameter.kind == pyinspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )

    if supports_var_kwargs:
        return func(**kwargs)

    filtered = {key: value for key, value in kwargs.items() if key in parameters}
    return func(**filtered)


def _extract_any(mapping: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        if key in mapping:
            value = _as_str(mapping[key])
            if value:
                return value
    return ""


def _parse_piicatcher_output(output: Any) -> Dict[str, Dict[str, List[str]]]:
    rows: List[Any]
    if output is None:
        return {}
    if hasattr(output, "to_dict"):
        try:
            rows = output.to_dict(orient="records")
        except Exception:
            rows = [output]
    elif isinstance(output, list):
        rows = output
    elif isinstance(output, tuple):
        rows = list(output)
    else:
        rows = [output]

    columns_by_table: Dict[str, Dict[str, List[str]]] = {}

    def add_match(table_key: str, column_name: str, pii_type: str) -> None:
        if not table_key or not column_name:
            return
        table_entry = columns_by_table.setdefault(table_key, {})
        pii_types = table_entry.setdefault(column_name, [])
        if pii_type and pii_type not in pii_types:
            pii_types.append(pii_type)

    for row in rows:
        schema_name = ""
        table_name = ""
        column_name = ""
        pii_type = ""

        if isinstance(row, Mapping):
            schema_name = _extract_any(row, ["schema_name", "schema"])
            table_name = _extract_any(row, ["table_name", "table"])
            column_name = _extract_any(row, ["column_name", "column"])
            pii_type = _extract_any(
                row,
                [
                    "pii_type",
                    "entity_type",
                    "detected_type",
                    "detector",
                    "detection_type",
                    "check_result",
                ],
            )
        elif isinstance(row, (tuple, list)):
            values = list(row)
            if len(values) >= 4:
                schema_name = _as_str(values[0])
                table_name = _as_str(values[1])
                column_name = _as_str(values[2])
                pii_type = _as_str(values[3])
        else:
            schema_name = _as_str(getattr(row, "schema_name", ""))
            table_name = _as_str(getattr(row, "table_name", ""))
            column_name = _as_str(getattr(row, "column_name", ""))
            pii_type = _as_str(
                getattr(
                    row,
                    "pii_type",
                    getattr(row, "entity_type", getattr(row, "detector", "")),
                )
            )

        if not table_name or not column_name:
            continue

        table_key = table_name.lower()
        if schema_name:
            table_key = f"{schema_name.lower()}.{table_key}"
        column_key = column_name.lower()
        add_match(table_key, column_key, pii_type)

    return columns_by_table


def _normalize_filter_values(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned if cleaned else None
    if isinstance(value, list):
        output: List[str] = []
        for item in value:
            if isinstance(item, dict):
                text = _as_str(item.get("name"))
            else:
                text = _as_str(item)
            if text:
                output.append(text)
        return output or None
    return value


def _build_scan_kwargs(connection_cfg: Dict[str, Any]) -> Dict[str, Any]:
    include_tables = connection_cfg.get("include_tables") or connection_cfg.get("tables")
    exclude_tables = connection_cfg.get("exclude_tables")
    include_schemas = connection_cfg.get("include_schemas") or connection_cfg.get(
        "include_schema"
    )
    exclude_schemas = connection_cfg.get("exclude_schemas") or connection_cfg.get(
        "exclude_schema"
    )

    scan_kwargs: Dict[str, Any] = {}
    include_tables = _normalize_filter_values(include_tables)
    if include_tables:
        scan_kwargs["include_table"] = include_tables
    exclude_tables = _normalize_filter_values(exclude_tables)
    if exclude_tables:
        scan_kwargs["exclude_table"] = exclude_tables
    include_schemas = _normalize_filter_values(include_schemas)
    if include_schemas:
        scan_kwargs["include_schema"] = include_schemas
    exclude_schemas = _normalize_filter_values(exclude_schemas)
    if exclude_schemas:
        scan_kwargs["exclude_schema"] = exclude_schemas

    scan_type = _as_str(connection_cfg.get("scan_type"))
    if scan_type:
        scan_kwargs["scan_type"] = scan_type
    return scan_kwargs


def _unsupported_source_error(
    source_type: str,
    function_candidates: Sequence[str],
) -> str:
    candidates_text = ", ".join(function_candidates)
    supported_text = ", ".join(DBCAT_DOC_SUPPORTED_SOURCE_TYPES)
    return (
        f"Unsupported piicatcher/dbcat source type '{source_type}'. "
        f"No add-source function found (tried: {candidates_text}). "
        f"Documented dbcat source types: {supported_text}. "
        "For RDS, use its engine type (mysql/postgresql). "
        "For other databases, set `piicatcher.add_source_function_candidates` only if "
        "your installed dbcat build provides that source function."
    )


def detect_pii_columns_with_piicatcher(
    *,
    connection_name: str,
    connection_url: str,
    connection_cfg: Dict[str, Any],
    piicatcher_cfg: Dict[str, Any],
) -> Tuple[Dict[str, Dict[str, List[str]]], Dict[str, Any], Optional[str]]:
    """
    Run piicatcher against a configured source and return discovered PII columns.

    Returns:
    - columns_by_table: {"table_name": {"column_name": ["PII_TYPE", ...]}}
    - metadata: non-sensitive run metadata for reporting
    - error: None on success, otherwise a user-facing error message
    """
    source_type = _as_str(
        piicatcher_cfg.get("source_type")
        or derive_source_type_from_connection(connection_url, connection_cfg)
    ).lower()
    if not source_type:
        return {}, {}, (
            "Unable to determine piicatcher source type. "
            "Set connection.type or sources.database.piicatcher.source_type."
        )

    _apply_pyopenssl_compat_shim()
    _install_snowflake_sqlalchemy_stub(source_type)
    _install_goog_stats_stub()

    try:
        from dbcat import api as dbcat_api
        from piicatcher.api import scan_database
    except Exception as exc:
        return {}, {}, (
            "piicatcher/dbcat import failed. "
            "Install piicatcher in a compatible runtime (Python 3.8-3.10). "
            f"Import error: {exc}"
        )

    source_name = _as_str(piicatcher_cfg.get("source_name") or connection_name) or connection_name
    catalog_path = _as_str(piicatcher_cfg.get("catalog_path") or ":memory:")
    app_dir = _as_str(piicatcher_cfg.get("app_dir") or ".piicatcher")
    secret = _as_str(piicatcher_cfg.get("secret") or "piicatcher-default-secret")

    derived_kwargs = _derive_source_kwargs(source_type, connection_url, connection_cfg)
    source_kwargs = _deep_merge(
        derived_kwargs,
        piicatcher_cfg.get("source_kwargs", {}) or {},
    )

    configured_candidates = piicatcher_cfg.get("add_source_function_candidates", []) or []
    function_candidates = [_as_str(name) for name in configured_candidates if _as_str(name)]
    if not function_candidates:
        function_candidates = _default_source_function_candidates(source_type)

    add_source_func = None
    selected_function_name = ""
    for function_name in function_candidates:
        candidate = getattr(dbcat_api, function_name, None)
        if callable(candidate):
            add_source_func = candidate
            selected_function_name = function_name
            break

    if add_source_func is None:
        return {}, {}, _unsupported_source_error(source_type, function_candidates)

    extra_scan_kwargs = _build_scan_kwargs(connection_cfg)

    try:
        catalog = _call_with_supported_kwargs(
            dbcat_api.open_catalog,
            {
                "path": catalog_path,
                "app_dir": app_dir,
                "secret": secret,
            },
        )
        with catalog.managed_session:
            source = _call_with_supported_kwargs(
                add_source_func,
                {
                    "catalog": catalog,
                    "name": source_name,
                    **source_kwargs,
                },
            )
            output = _call_with_supported_kwargs(
                scan_database,
                {
                    "catalog": catalog,
                    "source": source,
                    **extra_scan_kwargs,
                },
            )
    except Exception as exc:
        return {}, {}, f"piicatcher scan failed for connection '{connection_name}': {exc}"

    columns_by_table = _parse_piicatcher_output(output)
    pii_columns = {
        f"{table_key}.{column_name}"
        for table_key, columns in columns_by_table.items()
        for column_name in columns.keys()
    }
    pii_column_count = len(pii_columns)
    metadata = {
        "source_type": source_type,
        "source_name": source_name,
        "catalog_path": catalog_path,
        "add_source_function": selected_function_name,
        "table_count": len(columns_by_table),
        "pii_column_count": pii_column_count,
        "scan_options": extra_scan_kwargs,
    }
    return columns_by_table, metadata, None
