"""Configuration loading and resolution utilities for the scanner."""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional


SCAN_DEFAULTS: Dict[str, Any] = {
    "input_paths": ["."],
    "recursive": True,
    "include_extensions": [
        ".txt",
        ".csv",
        ".json",
        ".log",
        ".md",
        ".xml",
        ".yaml",
        ".yml",
        ".pdf",
        ".docx",
        ".png",
        ".jpg",
        ".jpeg",
    ],
    "exclude_dirs": [
        ".git",
        ".idea",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
    ],
    "exclude_file_globs": ["*.pyc", "*.pyo", "*.DS_Store"],
    "max_file_size_mb": 20,
    "read_binary_files_as_text": False,
    "pdf_max_pages": 50,
    "ocr_images": False,
}

DATABASE_PROFILE_DEFAULT_DIR = "config/databases"


def _default_filesystem_location() -> Dict[str, Any]:
    return {
        "name": "local_filesystem",
        "enabled": True,
        "provider": "local",
        "input_paths": [*SCAN_DEFAULTS["input_paths"]],
        "recursive": bool(SCAN_DEFAULTS["recursive"]),
    }


DEFAULT_CONFIG: Dict[str, Any] = {
    "scan": deepcopy(SCAN_DEFAULTS),
    "presidio": {
        "language": "en",
        "supported_languages": ["en"],
        "nlp_engine_name": "spacy",
        "model_name": "en_core_web_lg",
        "entities": [
            "IN_AADHAAR",
            "IN_PAN",
            "IN_IFSC",
            "IN_UPI_ID",
            "IN_PASSPORT",
            "IN_BANK_ACCOUNT",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "PERSON",
            "LOCATION",
            "IN_ADDRESS",
            "CREDIT_CARD",
            "IBAN_CODE",
            "IP_ADDRESS",
        ],
        "score_threshold": 0.35,
        "entity_score_thresholds": {
            "PERSON": 0.6,
            "LOCATION": 0.55,
            "PHONE_NUMBER": 0.55,
            "EMAIL_ADDRESS": 0.6,
            "IN_BANK_ACCOUNT": 0.45,
        },
        "return_decision_process": False,
        "allow_list": [],
        "allow_list_match": "exact",
        "context_words": [],
        "spacy_max_length": 3000000,
        "chunk_size_chars": 200000,
        "chunk_overlap_chars": 500,
        "context_enhancer": {
            "enabled": True,
            "context_similarity_factor": 0.35,
            "min_score_with_context_similarity": 0.45,
            "context_prefix_count": 8,
            "context_suffix_count": 2,
        },
    },
    "custom_recognizers": {
        "enable_indian_identifiers": True,
        "aadhaar_checksum_validation": True,
        "upi_generic_pattern": False,
        "upi_handle_domains": [
            "upi",
            "ybl",
            "ibl",
            "axl",
            "paytm",
            "okhdfcbank",
            "okicici",
            "oksbi",
            "okaxis",
        ],
    },
    "rule_engine": {
        "enabled": True,
        "region": "india",
        "environment_variable": "DPDP_RULES_ENV",
        "default_environment": "default",
        "environment": "default",
        "base_rules_file": "config/pii_rules/india/base_rules.json",
        "environment_rules": {
            "default": "config/pii_rules/india/default_rules.json",
            "dev": "config/pii_rules/india/dev_rules.json",
            "qa": "config/pii_rules/india/qa_rules.json",
            "prod": "config/pii_rules/india/prod_rules.json",
        },
    },
    "sources": {
        "enabled_sources": ["filesystem"],
        "filesystem": {
            "enabled": True,
            "locations": [_default_filesystem_location()],
        },
        "database": {
            "enabled": False,
            "scanner": "piicatcher",
            "profile_dir": DATABASE_PROFILE_DEFAULT_DIR,
            "profiles": [],
            "profile_paths": [],
            "include_all_tables": True,
            "include_all_databases": True,
            "exclude_databases": [],
            "piicatcher": {
                "enabled": True,
                "catalog_path": ":memory:",
                "app_dir": ".piicatcher",
                "secret": "",
                "source_type": "",
                "source_name": "",
                "source_kwargs": {},
                "add_source_function_candidates": [],
            },
            "connections": [],
        },
    },
    "output": {
        "path": "output/output.json",
        "pretty": True,
        "include_text_snippet": True,
        "snippet_context_chars": 24,
        "include_analysis_explanation": False,
        "include_file_hash": True,
        "include_source_metadata": True,
        "mask_file_paths": False,
        "file_path_mask_mode": "full",
        "file_path_base_dir": "",
        "file_path_hash_salt": "",
    },
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge two dictionaries, with override values taking precedence."""
    merged = deepcopy(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def expand_env_values(obj: Any) -> Any:
    """Expand environment variables (e.g. ${HOME}) in string values."""
    if isinstance(obj, dict):
        return {key: expand_env_values(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [expand_env_values(item) for item in obj]
    if isinstance(obj, str):
        return os.path.expandvars(obj)
    return obj


def read_json_file(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_file(path: Path, data: Dict[str, Any], pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        if pretty:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        else:
            json.dump(data, handle, ensure_ascii=False)


def write_default_config(config_path: Path) -> None:
    """Write a starter config file to disk."""
    config_dir = config_path.expanduser().resolve().parent
    data = deepcopy(DEFAULT_CONFIG)
    if config_dir.name == "scanner" and config_dir.parent.name == "config":
        data["sources"]["database"]["profile_dir"] = "../databases"
    write_json_file(config_path, data, pretty=True)


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _as_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


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


def _as_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if not isinstance(value, list):
        return []

    output: List[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            output.append(text)
    return output


def _legacy_sources_from_plugins(config: Dict[str, Any]) -> Dict[str, Any]:
    plugin_cfg = _as_dict(config.get("plugins"))
    filesystem_cfg = _as_dict(plugin_cfg.get("filesystem"))
    database_cfg = _as_dict(plugin_cfg.get("database"))
    scan_cfg = _as_dict(config.get("scan"))

    default_location = _default_filesystem_location()
    default_location["name"] = "legacy_local_filesystem"
    if "input_paths" in scan_cfg:
        default_location["input_paths"] = _as_str_list(scan_cfg.get("input_paths")) or ["."]
    if "recursive" in scan_cfg:
        default_location["recursive"] = bool(scan_cfg.get("recursive", True))
    default_location["enabled"] = bool(filesystem_cfg.get("enabled", True))

    enabled_plugins = [
        name
        for name in _as_str_list(plugin_cfg.get("enabled_plugins"))
        if name in {"filesystem", "database"}
    ]

    return {
        "enabled_sources": enabled_plugins,
        "filesystem": {
            "enabled": bool(filesystem_cfg.get("enabled", True)),
            "locations": [default_location],
        },
        "database": deep_merge(DEFAULT_CONFIG["sources"]["database"], database_cfg),
    }


def _normalize_filesystem_sources(sources_cfg: Dict[str, Any], scan_cfg: Dict[str, Any]) -> Dict[str, Any]:
    filesystem_cfg = _as_dict(sources_cfg.get("filesystem"))
    raw_locations = filesystem_cfg.get("locations")
    locations: List[Dict[str, Any]] = []

    if isinstance(raw_locations, list):
        for index, item in enumerate(raw_locations, start=1):
            if not isinstance(item, dict):
                continue
            location = dict(item)
            location["name"] = str(location.get("name") or f"filesystem_{index}")
            location["enabled"] = bool(location.get("enabled", True))
            location["provider"] = str(location.get("provider") or "local").strip().lower() or "local"
            location["input_paths"] = _as_str_list(location.get("input_paths")) or _as_str_list(
                scan_cfg.get("input_paths")
            ) or ["."]
            if "recursive" not in location:
                location["recursive"] = bool(scan_cfg.get("recursive", True))
            locations.append(location)

    if not locations:
        default_location = _default_filesystem_location()
        default_location["input_paths"] = _as_str_list(scan_cfg.get("input_paths")) or ["."]
        default_location["recursive"] = bool(scan_cfg.get("recursive", True))
        locations = [default_location]

    normalized = dict(filesystem_cfg)
    if "enabled" not in normalized:
        normalized["enabled"] = True
    normalized["locations"] = locations
    return normalized


def _normalize_database_sources(sources_cfg: Dict[str, Any]) -> Dict[str, Any]:
    database_cfg = deep_merge(
        DEFAULT_CONFIG["sources"]["database"],
        _as_dict(sources_cfg.get("database")),
    )
    database_cfg["enabled"] = bool(database_cfg.get("enabled", False))
    database_cfg["scanner"] = "piicatcher"
    database_cfg["profile_dir"] = _as_str(
        database_cfg.get("profile_dir") or DATABASE_PROFILE_DEFAULT_DIR
    )
    database_cfg["profiles"] = _as_str_list(database_cfg.get("profiles"))
    database_cfg["profile_paths"] = _as_str_list(database_cfg.get("profile_paths"))
    database_cfg["include_all_tables"] = _as_bool(
        database_cfg.get("include_all_tables"), True
    )
    database_cfg["include_all_databases"] = _as_bool(
        database_cfg.get("include_all_databases"), True
    )
    database_cfg["exclude_databases"] = _as_str_list(database_cfg.get("exclude_databases"))
    database_cfg["piicatcher"] = deep_merge(
        DEFAULT_CONFIG["sources"]["database"]["piicatcher"],
        _as_dict(database_cfg.get("piicatcher")),
    )

    raw_connections = database_cfg.get("connections")
    if not isinstance(raw_connections, list):
        database_cfg["connections"] = []
    else:
        normalized_connections: List[Dict[str, Any]] = []
        for item in raw_connections:
            if not isinstance(item, dict):
                continue
            connection = dict(item)
            connection["enabled"] = bool(connection.get("enabled", True))
            connection["auth"] = _as_dict(connection.get("auth"))
            connection["piicatcher"] = _as_dict(connection.get("piicatcher"))
            if "include_all_tables" in connection:
                connection["include_all_tables"] = _as_bool(
                    connection.get("include_all_tables"),
                    bool(database_cfg.get("include_all_tables", True)),
                )
            if "include_all_databases" in connection:
                connection["include_all_databases"] = _as_bool(
                    connection.get("include_all_databases"),
                    bool(database_cfg.get("include_all_databases", True)),
                )
            if "exclude_databases" in connection:
                connection["exclude_databases"] = _as_str_list(
                    connection.get("exclude_databases")
                )
            normalized_connections.append(connection)
        database_cfg["connections"] = normalized_connections

    return database_cfg


def _resolve_config_dir(config_path: Optional[Path], config: Dict[str, Any]) -> Path:
    if config_path is not None:
        return config_path.expanduser().resolve().parent
    meta_dir = _as_str(_as_dict(config.get("_meta")).get("config_dir"))
    if meta_dir:
        return Path(meta_dir).expanduser().resolve()
    return Path.cwd().resolve()


def _resolve_database_profile_dir(
    database_cfg: Dict[str, Any],
    config_dir: Path,
    override_dir: Optional[str] = None,
) -> Path:
    raw_dir = _as_str(override_dir or database_cfg.get("profile_dir") or DATABASE_PROFILE_DEFAULT_DIR)
    if not raw_dir:
        raw_dir = DATABASE_PROFILE_DEFAULT_DIR
    path = Path(raw_dir).expanduser()
    if not path.is_absolute():
        path = (config_dir / path).resolve()
    return path


def _extract_database_profile(payload: Any, source_path: Path) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"Database profile {source_path} must contain a JSON object.")

    if isinstance(payload.get("database"), dict):
        return payload["database"]

    sources_cfg = payload.get("sources")
    if isinstance(sources_cfg, dict) and isinstance(sources_cfg.get("database"), dict):
        return sources_cfg["database"]

    if any(key in payload for key in ("connections", "piicatcher", "scanner", "sample_values")):
        return payload

    raise ValueError(
        f"Database profile {source_path} is missing a 'database' section."
    )


def _merge_database_configs(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    excluded_keys = {
        "connections",
        "enabled",
        "profile_dir",
        "profiles",
        "profile_paths",
        "profiles_resolved",
    }
    merged = deep_merge(
        base,
        {key: value for key, value in extra.items() if key not in excluded_keys},
    )

    base_connections = base.get("connections")
    extra_connections = extra.get("connections")
    merged_connections: List[Dict[str, Any]] = []
    if isinstance(base_connections, list):
        merged_connections.extend(
            [item for item in base_connections if isinstance(item, dict)]
        )
    if isinstance(extra_connections, list):
        merged_connections.extend(
            [item for item in extra_connections if isinstance(item, dict)]
        )
    if merged_connections:
        merged["connections"] = merged_connections
    return merged


def _resolve_profile_path(
    item: str,
    *,
    profile_dir: Path,
    config_dir: Path,
) -> Optional[Path]:
    raw_item = _as_str(item)
    if not raw_item:
        return None

    candidate = Path(raw_item).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    if "/" in raw_item or "\\" in raw_item:
        candidate_config = (config_dir / candidate).resolve()
        if candidate_config.exists():
            return candidate_config
        return (profile_dir / candidate).resolve()

    if candidate.suffix.lower() == ".json":
        return (profile_dir / candidate).resolve()

    candidate = (profile_dir / candidate)
    if candidate.suffix.lower() != ".json":
        candidate = candidate.with_suffix(".json")
    return candidate.resolve()


def apply_database_profiles(
    config: Dict[str, Any],
    config_path: Optional[Path],
    *,
    override_profiles: Optional[List[str]] = None,
    override_profile_dir: Optional[str] = None,
    override_profile_paths: Optional[List[str]] = None,
) -> List[Path]:
    """
    Load database profiles from disk and merge their settings into sources.database.
    Returns resolved profile paths that were successfully applied.
    """
    sources_cfg = _as_dict(config.get("sources"))
    database_cfg = _as_dict(sources_cfg.get("database"))

    config_dir = _resolve_config_dir(config_path, config)
    profile_dir = _resolve_database_profile_dir(
        database_cfg, config_dir, override_dir=override_profile_dir
    )

    profiles = (
        _as_str_list(override_profiles)
        if override_profiles is not None
        else _as_str_list(database_cfg.get("profiles"))
    )
    profile_paths = (
        _as_str_list(override_profile_paths)
        if override_profile_paths is not None
        else _as_str_list(database_cfg.get("profile_paths"))
    )
    if override_profiles is not None:
        database_cfg["profiles"] = profiles
    if override_profile_paths is not None:
        database_cfg["profile_paths"] = profile_paths

    resolved_paths: List[Path] = []
    seen_paths: set[str] = set()
    for item in [*profiles, *profile_paths]:
        profile_path = _resolve_profile_path(
            item,
            profile_dir=profile_dir,
            config_dir=config_dir,
        )
        if profile_path is None:
            continue
        profile_key = str(profile_path)
        if profile_key in seen_paths:
            continue
        if not profile_path.exists():
            raise FileNotFoundError(
                f"Database profile not found: {profile_path}"
            )

        profile_payload = expand_env_values(read_json_file(profile_path))
        profile_cfg = _extract_database_profile(profile_payload, profile_path)
        database_cfg = _merge_database_configs(database_cfg, profile_cfg)
        resolved_paths.append(profile_path)
        seen_paths.add(profile_key)

    if resolved_paths:
        database_cfg["profiles_resolved"] = [str(path) for path in resolved_paths]
    database_cfg["profile_dir"] = str(profile_dir)

    sources_cfg["database"] = database_cfg
    config["sources"] = sources_cfg
    return resolved_paths


def refresh_database_sources(config: Dict[str, Any]) -> None:
    """Re-normalize database sources after runtime overrides or profile merges."""
    sources_cfg = _as_dict(config.get("sources"))
    sources_cfg["database"] = _normalize_database_sources(sources_cfg)
    sources_cfg["enabled_sources"] = _normalize_enabled_sources(sources_cfg)
    config["sources"] = sources_cfg


def _normalize_enabled_sources(sources_cfg: Dict[str, Any]) -> List[str]:
    configured = [
        name
        for name in _as_str_list(sources_cfg.get("enabled_sources"))
        if name in {"filesystem", "database"}
    ]
    if configured:
        deduped: List[str] = []
        for name in configured:
            if name not in deduped:
                deduped.append(name)
        return deduped

    auto_enabled: List[str] = []
    if bool(_as_dict(sources_cfg.get("filesystem")).get("enabled", True)):
        auto_enabled.append("filesystem")
    if bool(_as_dict(sources_cfg.get("database")).get("enabled", False)):
        auto_enabled.append("database")
    if auto_enabled:
        return auto_enabled
    return ["filesystem"]


def _normalize_sources_config(merged_config: Dict[str, Any], user_config: Dict[str, Any]) -> None:
    sources_cfg = _as_dict(merged_config.get("sources"))
    if "sources" not in user_config and "plugins" in user_config:
        sources_cfg = deep_merge(sources_cfg, _legacy_sources_from_plugins(merged_config))

    scan_cfg = deep_merge(SCAN_DEFAULTS, _as_dict(merged_config.get("scan")))
    sources_cfg["filesystem"] = _normalize_filesystem_sources(sources_cfg, scan_cfg)
    sources_cfg["database"] = _normalize_database_sources(sources_cfg)
    sources_cfg["enabled_sources"] = _normalize_enabled_sources(sources_cfg)

    merged_config["scan"] = scan_cfg
    merged_config["sources"] = sources_cfg


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load and validate a JSON config file merged with defaults."""
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. "
            "Use --init-config to create a starter config file."
        )
    user_config = expand_env_values(read_json_file(config_path))
    merged_config = deep_merge(DEFAULT_CONFIG, user_config)
    _normalize_sources_config(merged_config, user_config)
    return merged_config


def resolve_config_path(cli_config: Optional[str]) -> Path:
    """
    Resolve configuration path with the following precedence:
    1) --config path passed by user
    2) config/scanner/<name>.json under current working directory
    3) <name>.json in current working directory
    4) config/scanner/<name>.json next to executable/script
    5) <name>.json next to executable/script
    """
    if cli_config:
        return Path(cli_config).expanduser()

    candidate_names: List[str] = ["scanner_config.json"]
    executable_stem = Path(sys.argv[0]).stem
    if executable_stem:
        candidate_names.append(f"{executable_stem}_config.json")

    search_dirs: List[Path] = [Path.cwd()]
    if getattr(sys, "frozen", False):
        search_dirs.append(Path(sys.argv[0]).resolve().parent)
    else:
        search_dirs.append(Path(__file__).resolve().parents[2])
        search_dirs.append(Path(sys.argv[0]).resolve().parent)

    seen = set()
    deduped_dirs: List[Path] = []
    for directory in search_dirs:
        key = str(directory)
        if key in seen:
            continue
        seen.add(key)
        deduped_dirs.append(directory)

    for directory in deduped_dirs:
        for name in candidate_names:
            nested = directory / "config" / "scanner" / name
            if nested.exists():
                return nested
            candidate = directory / name
            if candidate.exists():
                return candidate

    return Path("config/scanner/scanner_config.json")


def resolve_output_path(output_value: str, default_filename: str = "output.json") -> Path:
    """
    Resolve output destination.

    If output_value points to a directory (existing, explicitly ending with a path
    separator, or having no file extension), place the report inside that directory
    using default_filename.
    """
    if not output_value:
        return Path(default_filename)

    raw_value = output_value.strip()
    output_path = Path(raw_value).expanduser()

    if output_path.exists() and output_path.is_dir():
        return output_path / default_filename

    if raw_value.endswith("/") or raw_value.endswith("\\"):
        return output_path / default_filename

    if not output_path.exists() and output_path.suffix == "":
        return output_path / default_filename

    return output_path
