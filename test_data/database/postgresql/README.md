# PostgreSQL DB Test Data For DPDP Scanner

Reusable PostgreSQL setup assets for database PII scanning tests.

## Files

- `create_schema_and_seed.sql`: Creates `customers`, `payments`, and `employee_profiles` tables and inserts sample PII-like data.
- `drop_schema.sql`: Drops the sample database.
- `setup_postgres_sample.sh`: Creates/loads sample database and rows.
- `reset_postgres_sample.sh`: Drops and recreates sample database.
- `piicatcher_postgres_scanner_config.json`: DB-only scanner config template (new `sources` format).

## Prerequisites

- PostgreSQL server installed and running.
- `psql` CLI available in `PATH`.
- Project environment created with Python 3.10 (single venv):

```bash
python3 bootstrap_and_package.py --config automation_runner_config.json
source .venv/bin/activate
```

Alternative (DB setup script only):

```bash
./test_data/database/setup_piicatcher_env.sh
source .venv/bin/activate
```

Optional strict dependency validation:

```bash
DPDP_PIP_CHECK_STRICT=1 ./test_data/database/setup_piicatcher_env.sh
```

## Install PostgreSQL (if not installed)

macOS (Homebrew):

```bash
brew install postgresql
brew services start postgresql
```

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y postgresql postgresql-client
sudo systemctl enable --now postgresql
```

## Quick Setup

```bash
cd test_data/database/postgresql
./setup_postgres_sample.sh
```

Or from the repo root:

```bash
./test_data/database/setup_local_databases.sh --postgres
```

Optional connection variables:

```bash
PGADMIN_USER=postgres
PGADMIN_PASSWORD=
PGADMIN_DB=postgres
PGADMIN_HOST=127.0.0.1
PGADMIN_PORT=5432
PGADMIN_USE_SUDO=auto

PG_SAMPLE_DB=dpdp_scanner_sample
PG_SAMPLE_USER=dpdp_scanner
PG_SAMPLE_PASSWORD=dpdp_scanner
PG_SAMPLE_HOST=127.0.0.1
PG_SAMPLE_PORT=5432
```

On Ubuntu, prefer `PGADMIN_USE_SUDO=1` to leverage `sudo -u postgres` peer auth.
When running scans, set `DPDP_POSTGRES_PASSWORD` to match `PG_SAMPLE_PASSWORD`.

## Run DB Scan

From repository root:

```bash
source .venv/bin/activate
DPDP_POSTGRES_PASSWORD=dpdp_scanner python main.py --config test_data/database/postgresql/piicatcher_postgres_scanner_config.json
```

Output is written to `output/output.json`.

## Cleanup

```bash
psql -U postgres -d postgres -f test_data/database/postgresql/drop_schema.sql
```
