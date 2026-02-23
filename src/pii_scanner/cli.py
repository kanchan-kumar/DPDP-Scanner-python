"""CLI orchestration module; coordinates config, scanner, and output steps."""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import Optional, Sequence

from .config import (
    load_config,
    resolve_config_path,
    resolve_output_path,
    write_default_config,
    write_json_file,
)
from .logging_utils import configure_logging
from .scanner import run_scan


def _suppress_non_actionable_warnings() -> None:
    """Suppress runtime warnings which don't affect scanner correctness."""
    warnings.filterwarnings(
        "ignore",
        message="urllib3 v2 only supports OpenSSL 1.1.1+.*",
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for scanner execution."""
    parser = argparse.ArgumentParser(
        description="Presidio-based PII scanner with modular architecture."
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Path to JSON configuration file. "
            "If omitted, scanner looks in current directory and executable folder."
        ),
    )
    parser.add_argument(
        "--init-config",
        metavar="PATH",
        help="Create a starter config file and exit.",
    )
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        help="Override scan.input_paths from config (repeatable).",
    )
    parser.add_argument(
        "--output",
        help="Override output.path from config.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Log verbosity (DEBUG, INFO, WARNING, ERROR).",
    )
    parser.add_argument(
        "--rules-env",
        help=(
            "Override rule environment for this run "
            "(example: default, dev, qa, prod)."
        ),
    )
    parser.add_argument(
        "--mask-file-paths",
        action="store_true",
        help="Enable file path masking in output JSON.",
    )
    parser.add_argument(
        "--file-path-mask-mode",
        choices=["full", "basename", "relative", "hash", "redacted"],
        help="File path masking mode for output JSON.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run scanner CLI workflow as the process entrypoint."""
    _suppress_non_actionable_warnings()
    args = parse_args(argv)
    logger = configure_logging(args.log_level)
    logger.info("STEP_START: cli")

    if args.init_config:
        config_target = Path(args.init_config).expanduser()
        if config_target.exists():
            print(f"Config already exists: {config_target}")
            return 1
        write_default_config(config_target)
        logger.info("STEP_DONE: init_config")
        print(f"Created starter config: {config_target}")
        return 0

    logger.info("STEP_START: load_config")
    config_path = resolve_config_path(args.config)
    try:
        config = load_config(config_path)
    except Exception as exc:
        logger.error("STEP_FAILED: load_config")
        print(f"Failed to load config: {exc}", file=sys.stderr)
        return 1
    logger.info("STEP_DONE: load_config")

    config["_meta"] = {
        "config_path": str(config_path.resolve()),
        "config_dir": str(config_path.resolve().parent),
    }

    if args.paths:
        config["scan"]["input_paths"] = args.paths
    if args.output:
        config["output"]["path"] = args.output
    if args.rules_env:
        config.setdefault("rule_engine", {})
        config["rule_engine"]["environment"] = args.rules_env
    if args.mask_file_paths:
        config.setdefault("output", {})
        config["output"]["mask_file_paths"] = True
    if args.file_path_mask_mode:
        config.setdefault("output", {})
        config["output"]["file_path_mask_mode"] = args.file_path_mask_mode

    resolved_output_path = resolve_output_path(
        str(config["output"].get("path", "pii_output.json"))
    )
    config["output"]["path"] = str(resolved_output_path)

    logger.info("STEP_START: run_scan")
    try:
        report = run_scan(config, logger)
        pretty = bool(config["output"].get("pretty", True))
        write_json_file(resolved_output_path, report, pretty=pretty)
    except KeyboardInterrupt:
        logger.warning("STEP_ABORTED: run_scan")
        print("Scan interrupted by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        logger.error("STEP_FAILED: run_scan")
        print(f"PII scan failed: {exc}", file=sys.stderr)
        return 1
    logger.info("STEP_DONE: run_scan")

    print(
        f"PII scan completed. Files scanned: {report['stats']['files_scanned']} | "
        f"Findings: {report['stats']['total_findings']}"
    )
    print(f"Output JSON: {resolved_output_path.resolve()}")
    logger.info("STEP_DONE: cli")
    return 0
