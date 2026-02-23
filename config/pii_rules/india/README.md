# India PII Rule Files

This folder defines environment-aware PII detection rules for India.

## Files
- `base_rules.json`: Generic India baseline rules.
- `default_rules.json`: Default environment override.
- `dev_rules.json`: Development override (broader detection).
- `qa_rules.json`: QA override (balanced detection).
- `prod_rules.json`: Production override (strict precision).

## Rule Model
- `presidio_overrides`: Global Presidio overrides (`entities`, score thresholds, context words).
- `custom_recognizers_overrides`: Override custom recognizer behavior.
- `include_entities`: Entity types to force include.
- `exclude_entities`: Entity types to force exclude.
- `entities.<ENTITY_NAME>`: Per-entity controls:
  - `enabled`
  - `score_threshold`
  - `normalization` (`raw`, `digits`, `lower`)
  - `include_values` / `exclude_values`
  - `include_patterns` / `exclude_patterns`
  - `required_context` / `forbidden_context`
  - `min_length` / `max_length`
  - `context_window_chars`
- `additional_pattern_recognizers`: Extra regex recognizers (for example `IN_ADDRESS`).

## Environment Selection
Environment is selected in this order:
1. `rule_engine.environment_variable` (for example `DPDP_RULES_ENV`)
2. `rule_engine.environment`
3. `rule_engine.default_environment`

Example:
```bash
DPDP_RULES_ENV=prod python main.py --config scanner_config.json --path ./test_data --output /tmp/pii_report.json
```

Or with CLI override:
```bash
python main.py --config scanner_config.json --rules-env qa --path ./test_data --output /tmp/pii_report.json
```

## Extending Rules
To add a new India-specific entity:
1. Add the entity name to `presidio_overrides.entities`.
2. Add per-entity rule block under `entities`.
3. Add `additional_pattern_recognizers` entry with one or more regex patterns.
4. Adjust `include_entities` / `exclude_entities` per environment file.
