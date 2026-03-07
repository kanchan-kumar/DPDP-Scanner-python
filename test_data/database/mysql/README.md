# MySQL DB Test Data For DPDP Scanner

Reusable MySQL setup assets for database PII scanning tests.

## Files

- `create_schema_and_seed.sql`: Creates `dpdp_scanner_sample` schema and inserts sample PII-like data.
- `drop_schema.sql`: Drops sample schema.
- `setup_mysql_sample.sh`: Creates/loads sample schema and rows.
- `reset_mysql_sample.sh`: Drops and recreates sample schema.
- `piicatcher_mysql_scanner_config.json`: DB-only scanner config template (new `sources` format).

## Prerequisites

- MySQL server installed and running.
- `mysql` CLI available in `PATH`.
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

## Install MySQL (if not installed)

macOS (Homebrew):

```bash
brew install mysql
brew services start mysql
```

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y mysql-server
sudo systemctl enable --now mysql
```

## Quick Setup

```bash
cd test_data/database/mysql
./setup_mysql_sample.sh
```

Optional connection variables:

```bash
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
```

## Run DB Scan

From repository root:

```bash
source .venv/bin/activate
python main.py --config test_data/database/mysql/piicatcher_mysql_scanner_config.json
```

Output is written to `output/output.json`.

## Cleanup

```bash
mysql -u root < test_data/database/mysql/drop_schema.sql
```
