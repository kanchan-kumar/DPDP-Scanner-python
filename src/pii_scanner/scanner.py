"""Core scan orchestration workflow."""

from __future__ import annotations

from copy import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .plugins import RECORD_ERROR, RECORD_SKIP, RECORD_SOURCE, create_source_plugins
from .postprocessing import apply_postprocessing
from .reporting import build_finding, deduplicate_results
from .rules import apply_rule_set_to_config, load_effective_rule_set
from .utils import utc_now


def _analyze_chunked(
    analyzer: Any,
    text: str,
    presidio_cfg: Dict[str, Any],
) -> List[Any]:
    """
    Analyze text in chunks to avoid spaCy max-length failures on large files.
    Offsets from each chunk are translated back to the original text positions.
    """
    language = presidio_cfg.get("language", "en")
    entities = presidio_cfg.get("entities") or None
    score_threshold = float(presidio_cfg.get("score_threshold", 0.35))
    return_decision_process = bool(presidio_cfg.get("return_decision_process", False))
    context_words = presidio_cfg.get("context_words") or None
    allow_list = presidio_cfg.get("allow_list") or None
    allow_list_match = presidio_cfg.get("allow_list_match", "exact")

    chunk_size = int(presidio_cfg.get("chunk_size_chars", 200000))
    chunk_overlap = int(presidio_cfg.get("chunk_overlap_chars", 500))
    if chunk_size <= 0:
        chunk_size = len(text)
    chunk_overlap = max(0, min(chunk_overlap, max(0, chunk_size - 1)))

    if len(text) <= chunk_size:
        return analyzer.analyze(
            text=text,
            language=language,
            entities=entities,
            score_threshold=score_threshold,
            return_decision_process=return_decision_process,
            context=context_words,
            allow_list=allow_list,
            allow_list_match=allow_list_match,
        )

    merged_results: List[Any] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk_text = text[start:end]
        chunk_results = analyzer.analyze(
            text=chunk_text,
            language=language,
            entities=entities,
            score_threshold=score_threshold,
            return_decision_process=return_decision_process,
            context=context_words,
            allow_list=allow_list,
            allow_list_match=allow_list_match,
        )
        for item in chunk_results:
            adjusted = copy(item)
            adjusted.start = int(item.start) + start
            adjusted.end = int(item.end) + start
            merged_results.append(adjusted)

        if end >= len(text):
            break
        start = end - chunk_overlap

    return merged_results


def scan_text_source(
    analyzer: Any,
    source_path: str,
    source_text: str,
    content_hash: Optional[str],
    source_type: str,
    source_plugin: str,
    config: Dict[str, Any],
    source_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, object]], Optional[str]]:
    """Scan generic source text and return findings/error tuple."""
    presidio_cfg = config["presidio"]
    output_cfg = config["output"]
    rule_set = config.get("_resolved_rules", {}) or {}
    entity_rules = rule_set.get("entities", {}) or {}

    if not source_text.strip():
        return [], None

    entities = presidio_cfg.get("entities") or None

    try:
        results = _analyze_chunked(
            analyzer=analyzer,
            text=source_text,
            presidio_cfg=presidio_cfg,
        )
    except Exception as exc:
        return [], str(exc)

    results = deduplicate_results(results, source_text)
    thresholds = presidio_cfg.get("entity_score_thresholds", {}) or {}
    results = apply_postprocessing(
        results=results,
        text=source_text,
        entity_thresholds=thresholds,
        entity_rules=entity_rules,
    )

    if entities:
        entity_filter = set(entities)
        results = [result for result in results if result.entity_type in entity_filter]

    findings = [
        build_finding(
            result=result,
            text=source_text,
            file_path=source_path,
            file_hash=content_hash,
            output_cfg=output_cfg,
            source_type=source_type,
            source_plugin=source_plugin,
            source_metadata=source_metadata,
        )
        for result in results
    ]
    return findings, None


def _summarize_source_config(config: Dict[str, Any]) -> Dict[str, Any]:
    source_cfg = config.get("sources", {}) or {}
    filesystem_cfg = source_cfg.get("filesystem", {}) or {}
    database_cfg = source_cfg.get("database", {}) or {}

    location_summaries: List[Dict[str, Any]] = []
    for index, location in enumerate(filesystem_cfg.get("locations", []) or [], start=1):
        if not isinstance(location, dict):
            continue
        location_summaries.append(
            {
                "name": str(location.get("name") or f"filesystem_{index}"),
                "enabled": bool(location.get("enabled", True)),
                "provider": str(location.get("provider") or "local"),
                "path_count": len(location.get("input_paths", []) or []),
            }
        )

    connection_summaries: List[Dict[str, Any]] = []
    for index, connection in enumerate(database_cfg.get("connections", []) or [], start=1):
        if not isinstance(connection, dict):
            continue
        connection_summaries.append(
            {
                "name": str(connection.get("name") or f"database_{index}"),
                "enabled": bool(connection.get("enabled", True)),
                "type": str(connection.get("type") or ""),
                "piicatcher_enabled": bool(
                    (connection.get("piicatcher", {}) or {}).get(
                        "enabled",
                        (database_cfg.get("piicatcher", {}) or {}).get("enabled", True),
                    )
                ),
                "source_type": str(
                    (connection.get("piicatcher", {}) or {}).get(
                        "source_type",
                        (database_cfg.get("piicatcher", {}) or {}).get("source_type", ""),
                    )
                ),
                "tables": [
                    item.get("name", "")
                    if isinstance(item, dict)
                    else str(item)
                    for item in (
                        connection.get("include_tables")
                        or connection.get("tables", [])
                        or []
                    )
                ],
                "query_names": [
                    item.get("name", "")
                    if isinstance(item, dict)
                    else ""
                    for item in (connection.get("queries", []) or [])
                ],
            }
        )

    return {
        "enabled_sources": source_cfg.get("enabled_sources", []),
        "filesystem": {
            "enabled": bool(filesystem_cfg.get("enabled", True)),
            "location_count": len(location_summaries),
            "locations": location_summaries,
        },
        "database": {
            "enabled": bool(database_cfg.get("enabled", False)),
            "scanner": "piicatcher",
            "profile_dir": str(database_cfg.get("profile_dir", "")),
            "profiles": database_cfg.get("profiles", []),
            "profiles_resolved": database_cfg.get("profiles_resolved", []),
            "piicatcher": {
                "enabled": bool(
                    (database_cfg.get("piicatcher", {}) or {}).get("enabled", True)
                ),
                "source_type": str(
                    (database_cfg.get("piicatcher", {}) or {}).get("source_type", "")
                ),
            },
            "connection_count": len(connection_summaries),
            "connections": connection_summaries,
        },
    }


def run_scan(config: Dict[str, Any], logger: logging.Logger) -> Dict[str, object]:
    """Execute full scan lifecycle and return report payload."""
    scan_cfg = config["scan"]
    output_cfg = config["output"]
    output_path = Path(output_cfg.get("path", "output/output.json")).resolve()

    logger.info("STEP_START: load_rules")
    rule_set = load_effective_rule_set(config)
    apply_rule_set_to_config(config, rule_set)
    logger.info(
        "STEP_DONE: load_rules region=%s environment=%s files=%d",
        rule_set.get("metadata", {}).get("region", "n/a"),
        rule_set.get("metadata", {}).get("environment", "n/a"),
        len(rule_set.get("metadata", {}).get("files_loaded", []) or []),
    )

    analyzer: Optional[Any] = None

    source_plugins = create_source_plugins(config, output_path, logger)
    logger.info(
        "STEP_START: scan_sources plugin_count=%d plugins=%s",
        len(source_plugins),
        ",".join(plugin.plugin_name for plugin in source_plugins),
    )

    start_time = utc_now()
    source_reports: List[Dict[str, object]] = []
    all_findings: List[Dict[str, object]] = []
    files_scanned = 0
    files_skipped = 0
    files_failed = 0
    plugin_stats: Dict[str, Dict[str, int]] = {}
    source_index = 0

    for plugin in source_plugins:
        plugin_stats.setdefault(
            plugin.plugin_name,
            {"sources_scanned": 0, "sources_skipped": 0, "sources_failed": 0, "findings": 0},
        )
        logger.info("STEP_START: plugin_scan name=%s", plugin.plugin_name)
        try:
            for record in plugin.iter_records():
                source_index += 1
                plugin_summary = plugin_stats.setdefault(
                    record.plugin_name,
                    {
                        "sources_scanned": 0,
                        "sources_skipped": 0,
                        "sources_failed": 0,
                        "findings": 0,
                    },
                )
                source_metadata = dict(record.metadata or {})
                source_metadata.pop("precomputed_findings", None)

                if record.record_type == RECORD_SKIP:
                    files_skipped += 1
                    plugin_summary["sources_skipped"] += 1
                    source_reports.append(
                        {
                            "file_path": record.source_path,
                            "status": "skipped",
                            "reason": record.reason,
                            "source_type": record.source_type,
                            "source_plugin": record.plugin_name,
                            "source_metadata": source_metadata,
                        }
                    )
                    continue

                if record.record_type == RECORD_ERROR:
                    files_failed += 1
                    plugin_summary["sources_failed"] += 1
                    source_reports.append(
                        {
                            "file_path": record.source_path,
                            "status": "failed",
                            "error": record.reason,
                            "findings_count": 0,
                            "source_type": record.source_type,
                            "source_plugin": record.plugin_name,
                            "source_metadata": source_metadata,
                        }
                    )
                    continue

                if record.record_type != RECORD_SOURCE:
                    files_failed += 1
                    plugin_summary["sources_failed"] += 1
                    source_reports.append(
                        {
                            "file_path": record.source_path,
                            "status": "failed",
                            "error": f"Unknown source record type: {record.record_type}",
                            "findings_count": 0,
                            "source_type": record.source_type,
                            "source_plugin": record.plugin_name,
                            "source_metadata": source_metadata,
                        }
                    )
                    continue

                if record.precomputed_findings:
                    files_scanned += 1
                    plugin_summary["sources_scanned"] += 1
                    all_findings.extend(record.precomputed_findings)
                    plugin_summary["findings"] += len(record.precomputed_findings)
                    source_reports.append(
                        {
                            "file_path": record.source_path,
                            "status": "scanned",
                            "findings_count": len(record.precomputed_findings),
                            "source_type": record.source_type,
                            "source_plugin": record.plugin_name,
                            "source_metadata": source_metadata,
                        }
                    )
                    continue

                if analyzer is None:
                    logger.info("STEP_START: build_analyzer")
                    from .recognizers import build_analyzer

                    analyzer = build_analyzer(config, logger)
                    logger.info("STEP_DONE: build_analyzer")

                findings, error = scan_text_source(
                    analyzer=analyzer,
                    source_path=record.source_path,
                    source_text=record.text,
                    content_hash=record.content_hash,
                    source_type=record.source_type,
                    source_plugin=record.plugin_name,
                    config=config,
                    source_metadata=source_metadata,
                )
                files_scanned += 1
                plugin_summary["sources_scanned"] += 1

                if error:
                    files_failed += 1
                    plugin_summary["sources_failed"] += 1
                    source_reports.append(
                        {
                            "file_path": record.source_path,
                            "status": "failed",
                            "error": error,
                            "findings_count": 0,
                            "source_type": record.source_type,
                            "source_plugin": record.plugin_name,
                            "source_metadata": source_metadata,
                        }
                    )
                else:
                    all_findings.extend(findings)
                    plugin_summary["findings"] += len(findings)
                    source_reports.append(
                        {
                            "file_path": record.source_path,
                            "status": "scanned",
                            "findings_count": len(findings),
                            "source_type": record.source_type,
                            "source_plugin": record.plugin_name,
                            "source_metadata": source_metadata,
                        }
                    )

                if source_index % 25 == 0:
                    logger.info(
                        "STEP_PROGRESS: scan_sources scanned=%d skipped=%d failed=%d findings=%d",
                        files_scanned,
                        files_skipped,
                        files_failed,
                        len(all_findings),
                    )
        except Exception as exc:
            files_failed += 1
            plugin_stats[plugin.plugin_name]["sources_failed"] += 1
            source_reports.append(
                {
                    "file_path": f"{plugin.source_type}://{plugin.plugin_name}",
                    "status": "failed",
                    "error": str(exc),
                    "findings_count": 0,
                    "source_type": plugin.source_type,
                    "source_plugin": plugin.plugin_name,
                }
            )
        logger.info("STEP_DONE: plugin_scan name=%s", plugin.plugin_name)

    end_time = utc_now()
    logger.info(
        "STEP_DONE: scan_sources scanned=%d skipped=%d failed=%d findings=%d",
        files_scanned,
        files_skipped,
        files_failed,
        len(all_findings),
    )

    return {
        "scanner": {
            "name": "presidio-dpdp-scanner",
            "version": "5.3.0",
        },
        "scan_started_at": start_time,
        "scan_completed_at": end_time,
        "config": {
            "scan": scan_cfg,
            "presidio": {
                "language": config["presidio"].get("language", "en"),
                "supported_languages": config["presidio"].get(
                    "supported_languages",
                    ["en"],
                ),
                "model_name": config["presidio"].get("model_name", "en_core_web_lg"),
                "score_threshold": config["presidio"].get("score_threshold", 0.35),
                "entities": config["presidio"].get("entities", []),
            },
            "custom_recognizers": config["custom_recognizers"],
            "rules": {
                "region": rule_set.get("metadata", {}).get("region"),
                "environment": rule_set.get("metadata", {}).get("environment"),
                "files_loaded": rule_set.get("metadata", {}).get("files_loaded", []),
                "include_entities": rule_set.get("include_entities", []),
                "exclude_entities": rule_set.get("exclude_entities", []),
            },
            "sources": _summarize_source_config(config),
        },
        "stats": {
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "files_failed": files_failed,
            "sources_scanned": files_scanned,
            "sources_skipped": files_skipped,
            "sources_failed": files_failed,
            "total_findings": len(all_findings),
            "plugin_summary": plugin_stats,
        },
        "findings": sorted(
            all_findings,
            key=lambda item: (
                item["file_path"],
                item["start"],
                item["end"],
                -item["score"],
            ),
        ),
        "files": source_reports,
    }
