# PII Scan Test Suite

This directory contains synthetic fixtures for validating the PII scanner with positive, negative, and edge-case scenarios.

## Structure
- positive/: files expected to trigger multiple entities
- negative/: files intended to contain no sensitive identifiers
- edge_cases/: near-matches, repeated values, large files, binary payloads, and skipped directory tests

## Quick Run
From repository root:

python main.py --config test_data/pii_scan_suite/scan_config_text_and_docs.json

Run with a specific rules environment:

DPDP_RULES_ENV=prod python main.py --config test_data/pii_scan_suite/scan_config_text_and_docs.json
python main.py --config test_data/pii_scan_suite/scan_config_text_and_docs.json --rules-env dev

## Notes
- All identifiers in this dataset are synthetic test values.
- OCR image fixtures are included but not scanned unless `ocr_images` is enabled and Tesseract is installed.
