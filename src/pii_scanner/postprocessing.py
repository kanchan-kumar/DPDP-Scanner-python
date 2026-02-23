"""Presidio result post-processing for accuracy and conflict reduction."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from presidio_analyzer import RecognizerResult

from .recognizers import verhoeff_validate

NUMERIC_CONTEXT_WINDOW = 64
BANK_CONTEXT_KEYWORDS = (
    "account",
    "acct",
    "a/c",
    "ifsc",
    "bank",
    "beneficiary",
    "iban",
)

ENTITY_PRIORITY: Dict[str, int] = {
    "IN_AADHAAR": 200,
    "IN_PAN": 190,
    "IN_IFSC": 185,
    "IN_UPI_ID": 180,
    "IN_PASSPORT": 175,
    "CREDIT_CARD": 170,
    "IBAN_CODE": 165,
    "US_BANK_NUMBER": 150,
    "IN_BANK_ACCOUNT": 145,
    "EMAIL_ADDRESS": 140,
    "PHONE_NUMBER": 130,
    "PERSON": 120,
    "LOCATION": 110,
    "IP_ADDRESS": 100,
}


def _result_sort_key(result: RecognizerResult) -> Tuple[int, int, float, int]:
    return (
        int(result.start),
        int(result.end),
        -float(result.score),
        -ENTITY_PRIORITY.get(result.entity_type, 0),
    )


def _entity_threshold(result: RecognizerResult, thresholds: Dict[str, float]) -> float:
    if result.entity_type in thresholds:
        return float(thresholds[result.entity_type])
    return 0.0


def _surrounding_text(text: str, start: int, end: int) -> str:
    snippet_start = max(0, start - NUMERIC_CONTEXT_WINDOW)
    snippet_end = min(len(text), end + NUMERIC_CONTEXT_WINDOW)
    return text[snippet_start:snippet_end].lower()


def _looks_like_phone(number: str) -> bool:
    return len(number) == 10 and number[:1] in {"6", "7", "8", "9"}


def _looks_like_aadhaar(number: str) -> bool:
    return len(number) == 12 and number[:1] in {"2", "3", "4", "5", "6", "7", "8", "9"} and verhoeff_validate(number)


def _should_keep_indian_bank_account(result: RecognizerResult, text: str) -> bool:
    matched = text[result.start : result.end]
    digits = re.sub(r"\D", "", matched)

    if len(digits) < 11 or len(digits) > 18:
        return False
    if _looks_like_phone(digits):
        return False
    if _looks_like_aadhaar(digits):
        return False

    if len(digits) <= 12:
        context = _surrounding_text(text, int(result.start), int(result.end))
        if not any(token in context for token in BANK_CONTEXT_KEYWORDS):
            return False
    return True


def _should_keep_phone_number(result: RecognizerResult, text: str) -> bool:
    """
    Tighten Indian number precision:
    - If number appears to be +91/91 format, local 10-digit part must start 6-9.
    """
    matched = text[result.start : result.end]
    digits = re.sub(r"\D", "", matched)
    if digits.startswith("91") and len(digits) >= 12:
        local = digits[-10:]
        if local and local[0] not in {"6", "7", "8", "9"}:
            return False
    return True


def _normalize_value(value: str, normalization: str) -> str:
    mode = normalization.lower().strip()
    if mode == "digits":
        return re.sub(r"\D", "", value)
    if mode == "lower":
        return value.lower()
    return value


def _matches_any_pattern(value: str, patterns: List[str]) -> bool:
    for pattern in patterns:
        try:
            if re.search(pattern, value, flags=re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def _should_keep_by_entity_rule(
    result: RecognizerResult,
    text: str,
    entity_rule: Dict[str, Any],
) -> bool:
    if not entity_rule:
        return True
    if entity_rule.get("enabled", True) is False:
        return False

    matched = text[result.start : result.end]
    normalization = str(entity_rule.get("normalization", "raw"))
    normalized_value = _normalize_value(matched, normalization)

    include_values = entity_rule.get("include_values", []) or []
    exclude_values = entity_rule.get("exclude_values", []) or []
    include_values_normalized = {
        _normalize_value(str(value), normalization) for value in include_values
    }
    exclude_values_normalized = {
        _normalize_value(str(value), normalization) for value in exclude_values
    }

    if include_values_normalized and normalized_value not in include_values_normalized:
        return False
    if normalized_value in exclude_values_normalized:
        return False

    include_patterns = [str(pattern) for pattern in (entity_rule.get("include_patterns", []) or [])]
    exclude_patterns = [str(pattern) for pattern in (entity_rule.get("exclude_patterns", []) or [])]
    if include_patterns and not _matches_any_pattern(matched, include_patterns):
        return False
    if exclude_patterns and _matches_any_pattern(matched, exclude_patterns):
        return False

    min_length = entity_rule.get("min_length")
    max_length = entity_rule.get("max_length")
    if min_length is not None and len(normalized_value) < int(min_length):
        return False
    if max_length is not None and len(normalized_value) > int(max_length):
        return False

    context_window = int(entity_rule.get("context_window_chars", NUMERIC_CONTEXT_WINDOW))
    context_window = max(0, context_window)
    snippet_start = max(0, int(result.start) - context_window)
    snippet_end = min(len(text), int(result.end) + context_window)
    surrounding = text[snippet_start:snippet_end].lower()

    required_context = [str(item).lower() for item in (entity_rule.get("required_context", []) or [])]
    forbidden_context = [str(item).lower() for item in (entity_rule.get("forbidden_context", []) or [])]

    if required_context and not any(token in surrounding for token in required_context):
        return False
    if forbidden_context and any(token in surrounding for token in forbidden_context):
        return False

    return True


def _resolve_same_span_conflicts(results: Sequence[RecognizerResult]) -> List[RecognizerResult]:
    grouped: Dict[Tuple[int, int], List[RecognizerResult]] = {}
    for result in results:
        grouped.setdefault((int(result.start), int(result.end)), []).append(result)

    resolved: List[RecognizerResult] = []
    for _, candidates in grouped.items():
        if len(candidates) == 1:
            resolved.append(candidates[0])
            continue

        winner = sorted(
            candidates,
            key=lambda item: (
                -ENTITY_PRIORITY.get(item.entity_type, 0),
                -float(item.score),
            ),
        )[0]
        resolved.append(winner)

    return sorted(resolved, key=_result_sort_key)


def apply_postprocessing(
    results: Iterable[RecognizerResult],
    text: str,
    entity_thresholds: Dict[str, float],
    entity_rules: Dict[str, Dict[str, Any]],
) -> List[RecognizerResult]:
    """
    Apply precision-focused post-processing:
    - per-entity score filtering
    - stricter numeric validation for IN_BANK_ACCOUNT
    - same-span conflict resolution using entity priority
    """
    filtered: List[RecognizerResult] = []
    for result in results:
        min_score = _entity_threshold(result, entity_thresholds)
        entity_rule = entity_rules.get(result.entity_type, {}) or {}
        if "score_threshold" in entity_rule:
            min_score = max(min_score, float(entity_rule["score_threshold"]))
        if float(result.score) < min_score:
            continue
        if not _should_keep_by_entity_rule(result, text, entity_rule):
            continue
        if result.entity_type == "IN_BANK_ACCOUNT":
            if not _should_keep_indian_bank_account(result, text):
                continue
        if result.entity_type == "PHONE_NUMBER":
            if not _should_keep_phone_number(result, text):
                continue
        filtered.append(result)

    return _resolve_same_span_conflicts(filtered)
