"""Configuration loading and resolution utilities for the scanner."""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_CONFIG: Dict[str, Any] = {
    "scan": {
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
    },
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
    "output": {
        "path": "pii_output.json",
        "pretty": True,
        "include_text_snippet": True,
        "snippet_context_chars": 24,
        "include_analysis_explanation": False,
        "include_file_hash": True,
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
    write_json_file(config_path, DEFAULT_CONFIG, pretty=True)


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load and validate a JSON config file merged with defaults."""
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. "
            "Use --init-config to create a starter config file."
        )
    user_config = expand_env_values(read_json_file(config_path))
    return deep_merge(DEFAULT_CONFIG, user_config)


def resolve_config_path(cli_config: Optional[str]) -> Path:
    """
    Resolve configuration path with the following precedence:
    1) --config path passed by user
    2) scanner_config.json in current working directory
    3) scanner_config.json or <executable>_config.json next to executable/script
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
            candidate = directory / name
            if candidate.exists():
                return candidate

    return Path("scanner_config.json")


def resolve_output_path(output_value: str, default_filename: str = "pii_output.json") -> Path:
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
