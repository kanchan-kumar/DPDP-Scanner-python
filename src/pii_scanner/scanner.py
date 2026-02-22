"""Core scan orchestration workflow."""

from __future__ import annotations

from copy import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from presidio_analyzer import AnalyzerEngine, RecognizerResult

from .discovery import iter_candidate_files
from .extractors import extract_text
from .postprocessing import apply_postprocessing
from .recognizers import build_analyzer
from .reporting import build_finding, deduplicate_results
from .utils import sha256_file, utc_now


def _analyze_chunked(
    analyzer: AnalyzerEngine,
    text: str,
    presidio_cfg: Dict[str, Any],
) -> List[RecognizerResult]:
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

    merged_results: List[RecognizerResult] = []
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


def scan_file(
    analyzer: AnalyzerEngine,
    path: Path,
    config: Dict[str, Any],
) -> Tuple[List[Dict[str, object]], Optional[str]]:
    """Scan one file and return findings/error tuple."""
    scan_cfg = config["scan"]
    presidio_cfg = config["presidio"]
    output_cfg = config["output"]

    try:
        text = extract_text(path, scan_cfg)
    except Exception as exc:
        return [], str(exc)

    if not text.strip():
        return [], None

    entities = presidio_cfg.get("entities") or None

    try:
        results = _analyze_chunked(
            analyzer=analyzer,
            text=text,
            presidio_cfg=presidio_cfg,
        )
    except Exception as exc:
        return [], str(exc)

    results = deduplicate_results(results, text)
    thresholds = presidio_cfg.get("entity_score_thresholds", {}) or {}
    results = apply_postprocessing(
        results=results,
        text=text,
        entity_thresholds=thresholds,
    )

    if entities:
        entity_filter = set(entities)
        results = [result for result in results if result.entity_type in entity_filter]

    include_file_hash = bool(output_cfg.get("include_file_hash", True))
    file_hash = sha256_file(path) if include_file_hash else None

    findings = [
        build_finding(
            result=result,
            text=text,
            file_path=path,
            file_hash=file_hash,
            output_cfg=output_cfg,
        )
        for result in results
    ]
    return findings, None


def run_scan(config: Dict[str, Any], logger: logging.Logger) -> Dict[str, object]:
    """Execute full scan lifecycle and return report payload."""
    scan_cfg = config["scan"]
    output_cfg = config["output"]
    output_path = Path(output_cfg.get("path", "pii_output.json")).resolve()
    max_size_bytes = int(scan_cfg.get("max_file_size_mb", 20) * 1024 * 1024)

    logger.info("STEP_START: build_analyzer")
    analyzer = build_analyzer(config, logger)
    logger.info("STEP_DONE: build_analyzer")

    logger.info("STEP_START: scan_files")
    start_time = utc_now()
    file_reports: List[Dict[str, object]] = []
    all_findings: List[Dict[str, object]] = []
    files_scanned = 0
    files_skipped = 0
    files_failed = 0

    paths = scan_cfg.get("input_paths", ["."])
    if isinstance(paths, str):
        paths = [paths]

    for index, file_path in enumerate(
        iter_candidate_files(
            input_paths=paths,
            recursive=bool(scan_cfg.get("recursive", True)),
            include_extensions=scan_cfg.get("include_extensions", []),
            exclude_dirs=scan_cfg.get("exclude_dirs", []),
            exclude_globs=scan_cfg.get("exclude_file_globs", []),
        ),
        start=1,
    ):
        try:
            resolved = file_path.resolve()
            if resolved == output_path:
                continue

            file_size = file_path.stat().st_size
            if file_size > max_size_bytes:
                files_skipped += 1
                file_reports.append(
                    {
                        "file_path": str(file_path),
                        "status": "skipped",
                        "reason": (
                            "File larger than max_file_size_mb "
                            f"({scan_cfg.get('max_file_size_mb')})"
                        ),
                    }
                )
                continue

            findings, error = scan_file(analyzer=analyzer, path=file_path, config=config)
            files_scanned += 1

            if error:
                files_failed += 1
                file_reports.append(
                    {
                        "file_path": str(file_path),
                        "status": "failed",
                        "error": error,
                        "findings_count": 0,
                    }
                )
                continue

            all_findings.extend(findings)
            file_reports.append(
                {
                    "file_path": str(file_path),
                    "status": "scanned",
                    "findings_count": len(findings),
                }
            )

        except Exception as exc:
            files_failed += 1
            file_reports.append(
                {
                    "file_path": str(file_path),
                    "status": "failed",
                    "error": str(exc),
                    "findings_count": 0,
                }
            )

        if index % 25 == 0:
            logger.info(
                "STEP_PROGRESS: scan_files scanned=%d skipped=%d failed=%d findings=%d",
                files_scanned,
                files_skipped,
                files_failed,
                len(all_findings),
            )

    end_time = utc_now()
    logger.info(
        "STEP_DONE: scan_files scanned=%d skipped=%d failed=%d findings=%d",
        files_scanned,
        files_skipped,
        files_failed,
        len(all_findings),
    )

    return {
        "scanner": {
            "name": "presidio-dpdp-scanner",
            "version": "5.0.0",
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
        },
        "stats": {
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "files_failed": files_failed,
            "total_findings": len(all_findings),
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
        "files": file_reports,
    }
