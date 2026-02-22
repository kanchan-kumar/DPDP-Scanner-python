"""Presidio analyzer and custom recognizer setup."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tldextract
except ImportError:  # pragma: no cover - optional runtime module
    tldextract = None

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider


def verhoeff_validate(number: str) -> bool:
    """Validate Verhoeff checksum (used by Aadhaar identifiers)."""
    mul = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
        [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
        [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
        [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
        [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
        [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
        [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
        [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
        [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
    ]
    perm = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
        [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
        [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
        [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
        [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
        [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
        [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
    ]

    checksum = 0
    for idx, digit in enumerate(reversed(number)):
        checksum = mul[checksum][perm[idx % 8][int(digit)]]
    return checksum == 0


class AadhaarRecognizer(PatternRecognizer):
    """Custom Aadhaar recognizer with optional checksum enforcement."""

    PATTERNS = [
        Pattern(
            name="aadhaar_strict",
            regex=r"(?<!\d)(?:[2-9]\d{3}\s?\d{4}\s?\d{4})(?!\d)",
            score=0.35,
        )
    ]

    def __init__(self, validate_checksum: bool = True, language: str = "en"):
        super().__init__(
            supported_entity="IN_AADHAAR",
            name="IN_AADHAAR_RECOGNIZER",
            supported_language=language,
            patterns=self.PATTERNS,
            context=["aadhaar", "uidai", "identity number", "government id"],
        )
        self.validate_checksum = validate_checksum

    def validate_result(self, pattern_text: str) -> Optional[bool]:
        digits = re.sub(r"\D", "", pattern_text)
        if len(digits) != 12:
            return False
        if not self.validate_checksum:
            return True
        return verhoeff_validate(digits)


def configure_tldextract_offline() -> None:
    """Force tldextract to use offline snapshot and writable temp cache."""
    if tldextract is None:
        return

    cache_dir = os.environ.get("TLDEXTRACT_CACHE")
    if not cache_dir:
        cache_dir = str(Path(tempfile.gettempdir()) / "tldextract-cache")
        os.environ["TLDEXTRACT_CACHE"] = cache_dir

    tldextract.extract = tldextract.TLDExtract(
        cache_dir=cache_dir,
        suffix_list_urls=(),
        fallback_to_snapshot=True,
    )


def build_indian_recognizers(language: str, aadhaar_checksum: bool) -> List[PatternRecognizer]:
    """Create custom pattern recognizers tailored for common India-specific IDs."""
    return [
        AadhaarRecognizer(validate_checksum=aadhaar_checksum, language=language),
        PatternRecognizer(
            supported_entity="IN_PAN",
            name="IN_PAN_RECOGNIZER",
            supported_language=language,
            patterns=[
                Pattern(
                    name="pan_regex",
                    regex=r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
                    score=0.55,
                )
            ],
            context=["pan", "income tax", "permanent account number"],
        ),
        PatternRecognizer(
            supported_entity="IN_IFSC",
            name="IN_IFSC_RECOGNIZER",
            supported_language=language,
            patterns=[
                Pattern(
                    name="ifsc_regex",
                    regex=r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
                    score=0.6,
                )
            ],
            context=["ifsc", "bank", "branch", "account"],
        ),
        PatternRecognizer(
            supported_entity="IN_UPI_ID",
            name="IN_UPI_RECOGNIZER",
            supported_language=language,
            patterns=[
                Pattern(
                    name="upi_strict",
                    regex=r"\b[a-zA-Z0-9._-]{2,}@(upi|ybl|ibl|axl|paytm|okhdfcbank|okicici|oksbi|okaxis)\b",
                    score=0.7,
                ),
                Pattern(
                    name="upi_generic",
                    regex=r"\b[a-zA-Z0-9._-]{2,}@[a-zA-Z]{2,64}\b",
                    score=0.45,
                ),
            ],
            context=["upi", "vpa", "gpay", "phonepe", "paytm", "bhim", "payment"],
        ),
        PatternRecognizer(
            supported_entity="IN_PASSPORT",
            name="IN_PASSPORT_RECOGNIZER",
            supported_language=language,
            patterns=[
                Pattern(
                    name="passport_regex",
                    regex=r"\b[A-PR-WYa-pr-wy][1-9]\d{6}\b",
                    score=0.55,
                )
            ],
            context=["passport", "travel document"],
        ),
        PatternRecognizer(
            supported_entity="IN_BANK_ACCOUNT",
            name="IN_BANK_ACCOUNT_RECOGNIZER",
            supported_language=language,
            patterns=[
                Pattern(
                    name="bank_account_regex",
                    regex=r"\b\d{9,18}\b",
                    score=0.35,
                )
            ],
            context=["account", "bank", "ifsc", "branch", "beneficiary"],
        ),
    ]


def build_analyzer(config: Dict[str, Any], logger: logging.Logger) -> AnalyzerEngine:
    """Construct AnalyzerEngine with predefined and custom recognizers."""
    presidio_cfg = config["presidio"]
    custom_cfg = config["custom_recognizers"]

    logger.info("STEP_START: configure_tldextract")
    configure_tldextract_offline()
    logger.info("STEP_DONE: configure_tldextract")

    logger.info("STEP_START: build_nlp_engine")
    supported_languages = presidio_cfg.get("supported_languages", ["en"])
    language = presidio_cfg.get("language", "en")
    model_name = presidio_cfg.get("model_name", "en_core_web_lg")
    nlp_engine_name = presidio_cfg.get("nlp_engine_name", "spacy")

    if language not in supported_languages:
        supported_languages = [language]

    nlp_configuration = {
        "nlp_engine_name": nlp_engine_name,
        "models": [{"lang_code": language, "model_name": model_name}],
    }

    provider = NlpEngineProvider(nlp_configuration=nlp_configuration)
    nlp_engine = provider.create_engine()
    logger.info("STEP_DONE: build_nlp_engine")

    logger.info("STEP_START: load_predefined_recognizers")
    registry = RecognizerRegistry(supported_languages=supported_languages)
    registry.load_predefined_recognizers(
        languages=supported_languages,
        nlp_engine=nlp_engine,
    )
    logger.info("STEP_DONE: load_predefined_recognizers")

    if custom_cfg.get("enable_indian_identifiers", True):
        logger.info("STEP_START: load_custom_recognizers")
        aadhaar_checksum = custom_cfg.get("aadhaar_checksum_validation", True)
        for recognizer in build_indian_recognizers(language, aadhaar_checksum):
            registry.add_recognizer(recognizer)
        logger.info("STEP_DONE: load_custom_recognizers")

    logger.info("STEP_START: init_analyzer_engine")
    analyzer = AnalyzerEngine(
        registry=registry,
        nlp_engine=nlp_engine,
        supported_languages=supported_languages,
        default_score_threshold=float(presidio_cfg.get("score_threshold", 0.35)),
    )
    logger.info("STEP_DONE: init_analyzer_engine")
    return analyzer

