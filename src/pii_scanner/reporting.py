"""Result transformation and report-friendly data shaping helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence

from presidio_analyzer import RecognizerResult


SENSITIVE_ENTITY_TYPES = {
    "IN_AADHAAR",
    "IN_PAN",
    "IN_PASSPORT",
    "CREDIT_CARD",
    "IBAN_CODE",
    "CRYPTO",
    "US_BANK_NUMBER",
}

PERSONAL_ENTITY_TYPES = {
    "PERSON",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "LOCATION",
    "IN_IFSC",
    "IN_UPI_ID",
    "IN_BANK_ACCOUNT",
}


def classify_entity(entity_type: str) -> str:
    """Map entity types to high-level DPDP categories."""
    if entity_type in SENSITIVE_ENTITY_TYPES:
        return "SENSITIVE_PERSONAL"
    if entity_type in PERSONAL_ENTITY_TYPES:
        return "PERSONAL"
    return "PERSONAL"


def deduplicate_results(results: Sequence[RecognizerResult], text: str) -> List[RecognizerResult]:
    """Remove duplicate recognizer results with same span/entity/value."""
    unique_keys = set()
    deduped: List[RecognizerResult] = []
    for result in sorted(results, key=lambda x: (x.start, x.end, -x.score, x.entity_type)):
        key = (
            result.entity_type,
            result.start,
            result.end,
            text[result.start : result.end],
        )
        if key in unique_keys:
            continue
        unique_keys.add(key)
        deduped.append(result)
    return deduped


def build_finding(
    result: RecognizerResult,
    text: str,
    file_path: Path,
    file_hash: Optional[str],
    output_cfg: Dict[str, object],
) -> Dict[str, object]:
    """Convert a Presidio result object into output JSON finding format."""
    matched_text = text[result.start : result.end]
    entity_type = result.entity_type
    finding: Dict[str, object] = {
        "entity_type": entity_type,
        "category": classify_entity(entity_type),
        "score": round(float(result.score), 4),
        "text": matched_text,
        "start": int(result.start),
        "end": int(result.end),
        "file_path": str(file_path),
    }

    if file_hash:
        finding["file_hash"] = file_hash

    recognizer_name = ""
    if result.recognition_metadata:
        recognizer_name = (
            result.recognition_metadata.get("recognizer_name")
            or result.recognition_metadata.get(
                RecognizerResult.RECOGNIZER_NAME_KEY,
                "",
            )
        )
    if recognizer_name:
        finding["recognizer_name"] = recognizer_name

    if output_cfg.get("include_text_snippet", True):
        context_chars = int(output_cfg.get("snippet_context_chars", 24))
        snippet_start = max(0, result.start - context_chars)
        snippet_end = min(len(text), result.end + context_chars)
        finding["snippet"] = text[snippet_start:snippet_end]

    if output_cfg.get("include_analysis_explanation", False) and result.analysis_explanation:
        finding["analysis_explanation"] = result.analysis_explanation.to_dict()

    return finding

