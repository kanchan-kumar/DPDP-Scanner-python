"""Logging helpers for structured, non-sensitive progress tracking."""

from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> logging.Logger:
    """
    Configure root logging once for the scanner runtime.

    Logs intentionally avoid sensitive payloads and focus on step names and progress.
    """
    normalized = (level or "INFO").upper()
    log_level = getattr(logging, normalized, logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.ERROR)

    logger = logging.getLogger("pii_scanner")
    logger.setLevel(log_level)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    else:
        for handler in logger.handlers:
            handler.setLevel(log_level)

    for noisy_logger in [
        "presidio-analyzer",
        "presidio_analyzer",
        "spacy",
        "thinc",
        "urllib3",
        "tldextract",
    ]:
        logging.getLogger(noisy_logger).setLevel(logging.ERROR)

    return logger
