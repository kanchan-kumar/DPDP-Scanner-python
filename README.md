# DPDP PII Scanner

A Presidio-based PII scanner with modular sources for filesystem and database
scanning. Database scanning is driven by per-database profiles so each machine
can select the right DB configuration without editing the main scanner config.

## What It Does

- Scan files and folders for PII with configurable rules and recognizers.
- Scan databases for PII columns using piicatcher/dbcat.
- Combine multiple sources (filesystem + database) in a single run.
- Emit a structured JSON report with findings and source metadata.

## Requirements

- Python 3.10 (project is tested on 3.10).
- Internet access on first bootstrap to install dependencies.
- DB credentials provided via environment variables where applicable.

For packaged runs, use the bundled `dpdp-scan` command and the included
configuration files.

## Quick Start (Packaged Build)

1) Build the package

```
python3 bootstrap_and_package.py --config automation_runner_config.json
```

2) Run with default config

```
./dpdp-scan
```

3) Run with explicit config

```
./dpdp-scan --config config/scanner/scanner_config.json
```

## Quick Start (Source)

1) Create and activate venv

```
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m spacy download en_core_web_lg
```

2) Run

```
python main.py --config config/scanner/scanner_config.json
```

## OS-Specific Build And Run

OS helper scripts live under `config/os`.

Ubuntu 24:
- Run the full setup + build + integration test script:

```
./config/os/setup_build_ubuntu24.sh
```

macOS:
- Build and run using the standard workflow:

```
python3 bootstrap_and_package.py --config automation_runner_config.json
./dist/dpdp-pii-scanner/dpdp-scan
```

Windows:
- Build with Python and run the packaged command:

```
python bootstrap_and_package.py --config automation_runner_config.json
dist\\dpdp-pii-scanner\\dpdp-scan.cmd
```

## Filesystem Scan

Example: scan `test_data` and write results to `output/output.json`.

```
./dpdp-scan --config config/scanner/scanner_config.json --path test_data --output output/output.json
```

## Database Scan (Profiles)

Database settings are stored as profiles in `config/databases`. Select a
profile at runtime without editing the main config.

### Enable DB scanning via CLI

```
DPDP_MYSQL_PASSWORD='' ./dpdp-scan --enable-db --db mysql_local
```

### Multiple profiles in one run

```
DPDP_MYSQL_PASSWORD='' DPDP_POSTGRES_PASSWORD='dpdp_scanner' \
  ./dpdp-scan --enable-db --db mysql_local --db postgres_local
```

### Use a custom profile folder

```
./dpdp-scan --enable-db --db mysql_local --db-config-dir /path/to/db_profiles
```

### Enable DB scanning via config

In `config/scanner/scanner_config.json`:

```
"sources": {
  "database": {
    "enabled": true,
    "profile_dir": "../databases",
    "profiles": ["mysql_local"]
  }
}
```

### Validation behavior

If DB scanning is enabled from the CLI (`--enable-db` or `--db`) and no
DB configuration is found, the scanner exits with an error:

```
Database scanning enabled from CLI but no database configuration was found.
Provide --db <profile> or configure sources.database.connections.
```

## Local Database Test Data

Sample MySQL/PostgreSQL datasets live under `test_data/database`. Use the
helper to install (optional) and seed the local databases:

```
./test_data/database/setup_local_databases.sh
```

Optional installs + env setup:

```
./test_data/database/setup_local_databases.sh --install
./test_data/database/setup_local_databases.sh --with-env
```

Run DB-only scans with the local run configs:

```
DPDP_MYSQL_PASSWORD='' ./dpdp-scan --config config/scanner/run_scanner_mysql_local.json
DPDP_POSTGRES_PASSWORD='dpdp_scanner' ./dpdp-scan --config config/scanner/run_scanner_postgres_local.json
```

## Database Profile Format

Each profile is a JSON object that contains a `database` section. Only the
`database` section is applied by the scanner. Example:

```
{
  "name": "mysql_local",
  "description": "Local MySQL sample",
  "labels": ["local", "mysql"],
  "database": {
    "connections": [
      {
        "name": "mysql_local_sample",
        "enabled": true,
        "type": "mysql",
        "url": "mysql://root:${DPDP_MYSQL_PASSWORD}@127.0.0.1:3306/dpdp_scanner_sample"
      }
    ]
  }
}
```

## Configuration Overview

Main config: `config/scanner/scanner_config.json`
Scanner config bundle (examples): `config/scanner/`

Top-level sections:
- `scan`: filesystem scan settings
- `presidio`: NLP + entity detection settings
- `custom_recognizers`: custom rules
- `rule_engine`: rule set overrides
- `sources`: source configuration (filesystem + database)
- `output`: report output settings

Database config keys:
- `sources.database.enabled`: enable/disable DB source
- `sources.database.profile_dir`: path to profiles folder
- `sources.database.profiles`: list of profile names to load
- `sources.database.profile_paths`: list of explicit profile JSON paths
- `sources.database.include_all_tables`: scan all tables when no include list is provided
- `sources.database.include_all_databases`: discover and scan all databases if none specified
- `sources.database.exclude_databases`: databases to skip during discovery
- `sources.database.connections`: direct inline connections (advanced)
- `sources.database.connections[].include_databases`: list of databases to scan
- `sources.database.connections[].exclude_databases`: list of databases to skip
- `sources.database.connections[].include_all_tables`: override table selection behavior
- `sources.database.connections[].include_all_databases`: override database discovery behavior

## Common Commands

- Initialize a starter config:

```
./dpdp-scan --init-config config/scanner/scanner_config.json
```

- Scan specific paths (repeatable):

```
./dpdp-scan --path /data/files --path /extra/share
```

- Change output file:

```
./dpdp-scan --output output/final_output.json
```

- Switch rules environment:

```
./dpdp-scan --rules-env prod
```

- Mask file paths in output:

```
./dpdp-scan --mask-file-paths --file-path-mask-mode hash
```

## Notes

- DB scanning uses `piicatcher` and `dbcat`.
- For RDS, set connection `type` and `url` according to engine.
- Use environment variables for secrets.
