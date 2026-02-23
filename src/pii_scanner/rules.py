"""Environment-aware PII rule loading and runtime config override helpers."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_environment_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    # If environment variable expansion was not resolved, treat as unset.
    if normalized.startswith("${") and normalized.endswith("}"):
        return None
    return normalized


def _resolve_environment(rule_engine_cfg: Dict[str, Any]) -> str:
    env_var_name = str(rule_engine_cfg.get("environment_variable", "")).strip()
    default_environment = str(rule_engine_cfg.get("default_environment", "default")).strip() or "default"

    env_from_var = None
    if env_var_name:
        env_from_var = _normalize_environment_name(os.getenv(env_var_name))
    env_from_cfg = _normalize_environment_name(rule_engine_cfg.get("environment"))
    return env_from_var or env_from_cfg or default_environment


def _resolve_rule_path(path_value: str, config_dir: Path) -> Path:
    candidate = Path(path_value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (config_dir / candidate).resolve()


def _resolve_rule_files(
    config: Dict[str, Any],
) -> Tuple[str, str, List[Path]]:
    rule_engine_cfg = config.get("rule_engine", {}) or {}
    config_dir = Path(
        config.get("_meta", {}).get("config_dir", Path.cwd())
    ).resolve()
    region = str(rule_engine_cfg.get("region", "india")).strip() or "india"
    environment = _resolve_environment(rule_engine_cfg)

    files: List[Path] = []
    base_rules_file = str(rule_engine_cfg.get("base_rules_file", "")).strip()
    if base_rules_file:
        files.append(_resolve_rule_path(base_rules_file, config_dir))

    env_rule_map = rule_engine_cfg.get("environment_rules", {}) or {}
    env_rule_value = env_rule_map.get(environment)
    if env_rule_value:
        files.append(_resolve_rule_path(str(env_rule_value), config_dir))

    return region, environment, files


def load_effective_rule_set(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Load and merge the effective rule set:
    - base rule file
    - optional environment override rule file
    """
    rule_engine_cfg = config.get("rule_engine", {}) or {}
    if not bool(rule_engine_cfg.get("enabled", False)):
        return {
            "metadata": {
                "enabled": False,
                "region": str(rule_engine_cfg.get("region", "india")),
                "environment": "disabled",
                "files_loaded": [],
            }
        }

    region, environment, files = _resolve_rule_files(config)
    merged_rules: Dict[str, Any] = {}
    loaded_files: List[str] = []

    for file_path in files:
        if not file_path.exists():
            raise FileNotFoundError(f"Rule file not found: {file_path}")
        merged_rules = _deep_merge(merged_rules, _read_json(file_path))
        loaded_files.append(str(file_path))

    merged_rules.setdefault("metadata", {})
    merged_rules["metadata"]["enabled"] = True
    merged_rules["metadata"]["region"] = region
    merged_rules["metadata"]["environment"] = environment
    merged_rules["metadata"]["files_loaded"] = loaded_files
    return merged_rules


def _merge_unique_list(current_values: List[str], new_values: List[str]) -> List[str]:
    merged: List[str] = []
    seen = set()
    for value in current_values + new_values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


def apply_rule_set_to_config(config: Dict[str, Any], rule_set: Dict[str, Any]) -> None:
    """
    Apply rule set overrides to runtime config.
    """
    config["_resolved_rules"] = rule_set
    if not rule_set.get("metadata", {}).get("enabled"):
        return

    presidio_cfg = config.setdefault("presidio", {})
    custom_cfg = config.setdefault("custom_recognizers", {})

    presidio_overrides = rule_set.get("presidio_overrides", {}) or {}
    custom_overrides = rule_set.get("custom_recognizers_overrides", {}) or {}
    entity_rules = rule_set.get("entities", {}) or {}

    if "entities" in presidio_overrides:
        presidio_cfg["entities"] = list(presidio_overrides.get("entities") or [])

    if "score_threshold" in presidio_overrides:
        presidio_cfg["score_threshold"] = float(presidio_overrides["score_threshold"])

    existing_thresholds = presidio_cfg.get("entity_score_thresholds", {}) or {}
    override_thresholds = presidio_overrides.get("entity_score_thresholds", {}) or {}
    merged_thresholds = dict(existing_thresholds)
    merged_thresholds.update(override_thresholds)

    for entity, entity_cfg in entity_rules.items():
        if isinstance(entity_cfg, dict) and "score_threshold" in entity_cfg:
            merged_thresholds[entity] = float(entity_cfg["score_threshold"])

    if merged_thresholds:
        presidio_cfg["entity_score_thresholds"] = merged_thresholds

    context_words = presidio_cfg.get("context_words", []) or []
    extra_context_words = presidio_overrides.get("context_words", []) or []
    presidio_cfg["context_words"] = _merge_unique_list(context_words, extra_context_words)

    include_entities = rule_set.get("include_entities", []) or []
    exclude_entities = rule_set.get("exclude_entities", []) or []

    effective_entities = presidio_cfg.get("entities", []) or []
    effective_entities = _merge_unique_list(list(effective_entities), list(include_entities))
    if exclude_entities:
        excluded = {str(name).strip() for name in exclude_entities if str(name).strip()}
        effective_entities = [entity for entity in effective_entities if entity not in excluded]
    if effective_entities:
        presidio_cfg["entities"] = effective_entities

    for key, value in custom_overrides.items():
        custom_cfg[key] = value
