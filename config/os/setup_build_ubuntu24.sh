#!/usr/bin/env bash
set -euo pipefail

# Ubuntu 24 setup + build script for DPDP Scanner.
#
# What it does:
# 1) Installs required system packages (apt)
# 2) Ensures Python 3.10 is available (via deadsnakes PPA if needed)
# 3) Creates/refreshes .venv with Python 3.10
# 4) Installs project requirements with piicatcher compatibility workaround
# 5) Installs spaCy model (with fallback wheel URLs)
# 6) Removes known PyInstaller blocker (pathlib backport)
# 7) Builds executable + zip using build_executable.py
# 8) Installs/configures MySQL + PostgreSQL sample data and runs scanner test
#    using the packaged launcher + config/scanner/run_scanner_mysql_postgres_and_files.json
#
# Usage:
#   ./config/os/setup_build_ubuntu24.sh
#
# Optional env vars:
#   DPDP_REPO_ROOT=/path/to/repo
#   DPDP_VENV_DIR=/path/to/venv
#   DPDP_PYTHON_BIN=python3.10
#   DPDP_DBCAT_INSTALL_SPEC=dbcat==0.14.2
#   DPDP_PIICATCHER_INSTALL_SPEC=git+https://github.com/tokern/piicatcher.git
#   DPDP_SPACY_MODEL=en_core_web_lg
#   DPDP_SKIP_SYSTEM_DEPS=0|1
#   DPDP_SKIP_SPACY_MODEL=0|1
#   DPDP_SKIP_MYSQL_SERVER=0|1
#   DPDP_SKIP_POSTGRES_SERVER=0|1
#   DPDP_SKIP_MYSQL_TEST=0|1
#   DPDP_SKIP_POSTGRES_TEST=0|1
#   DPDP_MYSQL_TEST_HOST=127.0.0.1
#   DPDP_MYSQL_TEST_PORT=3306
#   DPDP_MYSQL_TEST_USER=root
#   DPDP_MYSQL_TEST_PASSWORD=
#   DPDP_MYSQL_TEST_CONFIG=config/scanner/run_scanner_mysql_and_files.json
#   DPDP_MYSQL_TEST_OUTPUT=output/output.json
#   DPDP_POSTGRES_TEST_HOST=127.0.0.1
#   DPDP_POSTGRES_TEST_PORT=5432
#   DPDP_POSTGRES_TEST_USER=dpdp_scanner
#   DPDP_POSTGRES_TEST_PASSWORD=dpdp_scanner
#   DPDP_POSTGRES_TEST_DB=dpdp_scanner_sample
#   DPDP_POSTGRES_TEST_CONFIG=test_data/database/postgresql/piicatcher_postgres_scanner_config.json
#   DPDP_POSTGRES_TEST_OUTPUT=output/output.json
#   DPDP_INTEGRATION_TEST_CONFIG=config/scanner/run_scanner_mysql_postgres_and_files.json
#   DPDP_INTEGRATION_TEST_OUTPUT=output/output.json

log() {
  printf '[setup-build] %s\n' "$*"
}

die() {
  printf '[setup-build] ERROR: %s\n' "$*" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

apt_get() {
  if [ -n "${SUDO:-}" ]; then
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get "$@"
  else
    DEBIAN_FRONTEND=noninteractive apt-get "$@"
  fi
}

stop_mysql_service() {
  if command_exists systemctl; then
    $SUDO systemctl stop mysql >/dev/null 2>&1 || true
  fi
  if command_exists service; then
    $SUDO service mysql stop >/dev/null 2>&1 || true
  fi
  $SUDO pkill -f mysqld >/dev/null 2>&1 || true
}

mysql_root_exec() {
  if [ -n "${SUDO:-}" ]; then
    $SUDO mysql "$@"
  else
    mysql "$@"
  fi
}

postgres_admin_exec() {
  if command_exists sudo; then
    sudo -u postgres psql "$@"
    return
  fi
  if command_exists runuser; then
    runuser -u postgres -- psql "$@"
    return
  fi
  die "sudo or runuser is required to execute psql as the postgres user."
}

REPO_ROOT="${DPDP_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
VENV_DIR="${DPDP_VENV_DIR:-$REPO_ROOT/.venv}"
PYTHON_BIN="${DPDP_PYTHON_BIN:-python3.10}"
DBCAT_INSTALL_SPEC="${DPDP_DBCAT_INSTALL_SPEC:-dbcat==0.14.2}"
PIICATCHER_INSTALL_SPEC="${DPDP_PIICATCHER_INSTALL_SPEC:-git+https://github.com/tokern/piicatcher.git}"
SPACY_MODEL="${DPDP_SPACY_MODEL:-en_core_web_lg}"
SKIP_SYSTEM_DEPS="${DPDP_SKIP_SYSTEM_DEPS:-0}"
SKIP_SPACY_MODEL="${DPDP_SKIP_SPACY_MODEL:-0}"
SKIP_MYSQL_SERVER="${DPDP_SKIP_MYSQL_SERVER:-0}"
SKIP_POSTGRES_SERVER="${DPDP_SKIP_POSTGRES_SERVER:-0}"
SKIP_MYSQL_TEST="${DPDP_SKIP_MYSQL_TEST:-0}"
SKIP_POSTGRES_TEST="${DPDP_SKIP_POSTGRES_TEST:-0}"
MYSQL_TEST_HOST="${DPDP_MYSQL_TEST_HOST:-127.0.0.1}"
MYSQL_TEST_PORT="${DPDP_MYSQL_TEST_PORT:-3306}"
MYSQL_TEST_USER="${DPDP_MYSQL_TEST_USER:-root}"
MYSQL_TEST_PASSWORD="${DPDP_MYSQL_TEST_PASSWORD:-}"
MYSQL_TEST_CONFIG="${DPDP_MYSQL_TEST_CONFIG:-$REPO_ROOT/config/scanner/run_scanner_mysql_and_files.json}"
MYSQL_TEST_OUTPUT="${DPDP_MYSQL_TEST_OUTPUT:-$REPO_ROOT/output/output.json}"
POSTGRES_TEST_HOST="${DPDP_POSTGRES_TEST_HOST:-127.0.0.1}"
POSTGRES_TEST_PORT="${DPDP_POSTGRES_TEST_PORT:-5432}"
POSTGRES_TEST_USER="${DPDP_POSTGRES_TEST_USER:-dpdp_scanner}"
POSTGRES_TEST_PASSWORD="${DPDP_POSTGRES_TEST_PASSWORD:-dpdp_scanner}"
POSTGRES_TEST_DB="${DPDP_POSTGRES_TEST_DB:-dpdp_scanner_sample}"
POSTGRES_TEST_CONFIG="${DPDP_POSTGRES_TEST_CONFIG:-$REPO_ROOT/test_data/database/postgresql/piicatcher_postgres_scanner_config.json}"
POSTGRES_TEST_OUTPUT="${DPDP_POSTGRES_TEST_OUTPUT:-$REPO_ROOT/output/output.json}"
INTEGRATION_TEST_CONFIG="${DPDP_INTEGRATION_TEST_CONFIG:-$REPO_ROOT/config/scanner/run_scanner_mysql_postgres_and_files.json}"
INTEGRATION_TEST_OUTPUT="${DPDP_INTEGRATION_TEST_OUTPUT:-$REPO_ROOT/output/output.json}"

[ -f "$REPO_ROOT/build_executable.py" ] || die "build_executable.py not found under REPO_ROOT=$REPO_ROOT"
[ -f "$REPO_ROOT/requirements.txt" ] || die "requirements.txt not found under REPO_ROOT=$REPO_ROOT"
if [ "$SKIP_MYSQL_TEST" = "0" ]; then
  [ -f "$MYSQL_TEST_CONFIG" ] || die "MySQL test config not found: $MYSQL_TEST_CONFIG"
fi
if [ "$SKIP_POSTGRES_TEST" = "0" ]; then
  [ -f "$POSTGRES_TEST_CONFIG" ] || die "PostgreSQL test config not found: $POSTGRES_TEST_CONFIG"
fi
if [ "$SKIP_MYSQL_TEST" = "0" ] && [ "$SKIP_POSTGRES_TEST" = "0" ]; then
  [ -f "$INTEGRATION_TEST_CONFIG" ] || die "Integration test config not found: $INTEGRATION_TEST_CONFIG"
fi

if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  if [ "${ID:-}" != "ubuntu" ] || [ "${VERSION_ID%%.*}" != "24" ]; then
    die "This script is intended for Ubuntu 24.x. Found: ${PRETTY_NAME:-unknown}"
  fi
else
  die "/etc/os-release not found; cannot verify Ubuntu version"
fi

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  command_exists sudo || die "sudo is required when not running as root"
  SUDO="sudo"
fi

if [ "$SKIP_SYSTEM_DEPS" = "0" ]; then
  log "Installing base system dependencies..."
  apt_get update -y
  apt_get install -y \
    software-properties-common \
    ca-certificates \
    curl \
    git \
    build-essential \
    pkg-config \
    patchelf \
    libssl-dev \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libjpeg-dev \
    libpq-dev \
    tesseract-ocr

  log "Installing database client libraries..."
  apt_get install -y \
    default-libmysqlclient-dev \
    mysql-client \
    postgresql-client

  if [ "$SKIP_MYSQL_TEST" = "0" ] && [ "$SKIP_MYSQL_SERVER" = "0" ]; then
    log "Installing MySQL server..."
    stop_mysql_service
    if ! apt_get install -y mysql-server; then
      log "MySQL server install failed; attempting dpkg recovery..."
      stop_mysql_service
      $SUDO dpkg --configure -a || true
      apt_get install -y mysql-server
    fi
  fi

  if [ "$SKIP_POSTGRES_TEST" = "0" ] && [ "$SKIP_POSTGRES_SERVER" = "0" ]; then
    log "Installing PostgreSQL server..."
    apt_get install -y postgresql
  fi
fi

if ! command_exists python3.10; then
  if [ "$SKIP_SYSTEM_DEPS" = "1" ]; then
    die "python3.10 not found and DPDP_SKIP_SYSTEM_DEPS=1; install python3.10 manually."
  fi
  log "python3.10 not found. Adding deadsnakes PPA..."
  $SUDO add-apt-repository -y ppa:deadsnakes/ppa
  apt_get update -y
  if ! apt_get install -y python3.10 python3.10-venv python3.10-dev python3.10-distutils; then
    log "python3.10-distutils not available; retrying without it..."
    apt_get install -y python3.10 python3.10-venv python3.10-dev
  fi
fi

if ! command_exists "$PYTHON_BIN"; then
  die "Python binary not found: $PYTHON_BIN"
fi

PY_MM="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [ "$PY_MM" != "3.10" ]; then
  die "Unsupported Python from $PYTHON_BIN: $PY_MM (required: 3.10.x)"
fi

log "Creating virtual environment: $VENV_DIR"
"$PYTHON_BIN" -m venv --clear "$VENV_DIR"
VENV_PY="$VENV_DIR/bin/python"
[ -x "$VENV_PY" ] || die "venv python not found: $VENV_PY"

log "Upgrading bootstrap tooling in venv..."
"$VENV_PY" -m pip install --upgrade "pip<26" "setuptools<81" wheel "poetry-core>=1.7,<3"

TMP_REQ="$(mktemp)"
trap 'rm -f "$TMP_REQ"' EXIT

log "Installing non-piicatcher requirements..."
grep -Ev '^[[:space:]]*(piicatcher|dbcat)([[:space:]]|@|=|$)' "$REPO_ROOT/requirements.txt" > "$TMP_REQ" || true
"$VENV_PY" -m pip install --no-build-isolation --prefer-binary -r "$TMP_REQ"

log "Installing dbcat with ignore-requires-python..."
"$VENV_PY" -m pip install --no-build-isolation --prefer-binary --ignore-requires-python \
  "$DBCAT_INSTALL_SPEC"

log "Installing piicatcher with ignore-requires-python..."
"$VENV_PY" -m pip install --no-build-isolation --prefer-binary --ignore-requires-python \
  "piicatcher @ $PIICATCHER_INSTALL_SPEC"

log "Re-applying compatibility pins..."
"$VENV_PY" -m pip install --no-build-isolation --upgrade \
  "presidio-analyzer>=2.2.0,<3" \
  "presidio-anonymizer>=2.2.0,<3" \
  "spacy>=3.4.4,<3.7" \
  "pydantic>=1.10.2,<2" \
  "thinc<8.2" \
  "typer>=0.4,<0.5" \
  "cryptography<46"

if ! "$VENV_PY" -m pip check; then
  log "WARNING: pip check reports conflicts (expected with piicatcher/dbcat stack on some envs)."
fi

if [ "$SKIP_SPACY_MODEL" = "0" ]; then
  log "Installing spaCy model: $SPACY_MODEL"
  if ! "$VENV_PY" -m spacy download "$SPACY_MODEL"; then
    log "spaCy download failed; attempting wheel URL fallback."
    SPACY_VERSION="$("$VENV_PY" -c 'import spacy; print(spacy.__version__)')"
    MAJOR_MINOR="${SPACY_VERSION%.*}"
    FALLBACK_CANDIDATES=("$SPACY_VERSION" "${MAJOR_MINOR}.0")

    INSTALLED=0
    for version in "${FALLBACK_CANDIDATES[@]}"; do
      WHEEL_URL="https://github.com/explosion/spacy-models/releases/download/${SPACY_MODEL}-${version}/${SPACY_MODEL}-${version}-py3-none-any.whl"
      if "$VENV_PY" -m pip install --upgrade --no-deps "$WHEEL_URL"; then
        INSTALLED=1
        break
      fi
    done

    if [ "$INSTALLED" -ne 1 ]; then
      die "Failed to install spaCy model '$SPACY_MODEL'."
    fi
  fi
fi

log "Removing obsolete pathlib backport (PyInstaller blocker) if present..."
"$VENV_PY" -m pip uninstall -y pathlib >/dev/null 2>&1 || true

log "Building executable package..."
(
  cd "$REPO_ROOT"
  "$VENV_PY" build_executable.py --name dpdp-pii-scanner --command-name dpdp-scan --zip
)

if [ "$SKIP_MYSQL_TEST" = "0" ]; then
  command_exists mysql || die "mysql client not found. Install mysql-client or set DPDP_SKIP_MYSQL_TEST=1."

  log "Starting MySQL service..."
  # Explicit Ubuntu step:
  # sudo systemctl enable --now mysql
  if command_exists systemctl; then
    if ! $SUDO systemctl enable --now mysql; then
      log "systemctl start failed; trying service mysql start..."
      $SUDO service mysql start
    fi
  else
    $SUDO service mysql start
  fi

  log "Waiting for MySQL to become ready..."
  MYSQL_READY=0
  for _ in $(seq 1 30); do
    if mysql_root_exec -e "SELECT 1;" >/dev/null 2>&1; then
      MYSQL_READY=1
      break
    fi
    sleep 1
  done
  [ "$MYSQL_READY" -eq 1 ] || die "MySQL is not ready."

  log "Seeding MySQL sample schema/data..."
  mysql_root_exec < "$REPO_ROOT/test_data/database/mysql/create_schema_and_seed.sql"

  ESC_MYSQL_USER=${MYSQL_TEST_USER//\'/\'\'}
  ESC_MYSQL_PASSWORD=${MYSQL_TEST_PASSWORD//\'/\'\'}

  log "Creating scanner user and grants..."
  mysql_root_exec <<SQL
CREATE USER IF NOT EXISTS '${ESC_MYSQL_USER}'@'127.0.0.1' IDENTIFIED BY '${ESC_MYSQL_PASSWORD}';
CREATE USER IF NOT EXISTS '${ESC_MYSQL_USER}'@'localhost' IDENTIFIED BY '${ESC_MYSQL_PASSWORD}';
GRANT ALL PRIVILEGES ON dpdp_scanner_sample.* TO '${ESC_MYSQL_USER}'@'127.0.0.1';
GRANT ALL PRIVILEGES ON dpdp_scanner_sample.* TO '${ESC_MYSQL_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL

fi

if [ "$SKIP_POSTGRES_TEST" = "0" ]; then
  command_exists psql || die "psql client not found. Install postgresql-client or set DPDP_SKIP_POSTGRES_TEST=1."

  log "Starting PostgreSQL service..."
  # Explicit Ubuntu step:
  # sudo systemctl enable --now postgresql
  if command_exists systemctl; then
    if ! $SUDO systemctl enable --now postgresql; then
      log "systemctl start failed; trying service postgresql start..."
      $SUDO service postgresql start
    fi
  else
    $SUDO service postgresql start
  fi

  log "Waiting for PostgreSQL to become ready..."
  POSTGRES_READY=0
  if command_exists pg_isready; then
    for _ in $(seq 1 30); do
      if pg_isready -h "$POSTGRES_TEST_HOST" -p "$POSTGRES_TEST_PORT" >/dev/null 2>&1; then
        POSTGRES_READY=1
        break
      fi
      sleep 1
    done
  else
    for _ in $(seq 1 30); do
      if postgres_admin_exec -d postgres -tAc "SELECT 1;" >/dev/null 2>&1; then
        POSTGRES_READY=1
        break
      fi
      sleep 1
    done
  fi
  [ "$POSTGRES_READY" -eq 1 ] || die "PostgreSQL is not ready."

  ESC_POSTGRES_USER=${POSTGRES_TEST_USER//\'/\'\'}
  ESC_POSTGRES_PASSWORD=${POSTGRES_TEST_PASSWORD//\'/\'\'}
  ESC_POSTGRES_DB=${POSTGRES_TEST_DB//\'/\'\'}

  log "Creating PostgreSQL user/database and grants..."
  ROLE_EXISTS=$(postgres_admin_exec -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname = '${ESC_POSTGRES_USER}'" || true)
  if [ "$ROLE_EXISTS" != "1" ]; then
    postgres_admin_exec -d postgres -v ON_ERROR_STOP=1 -c "CREATE USER ${ESC_POSTGRES_USER} WITH PASSWORD '${ESC_POSTGRES_PASSWORD}';"
  fi

  DB_EXISTS=$(postgres_admin_exec -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '${ESC_POSTGRES_DB}'" || true)
  if [ "$DB_EXISTS" != "1" ]; then
    postgres_admin_exec -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${ESC_POSTGRES_DB};"
  fi

  postgres_admin_exec -d postgres -v ON_ERROR_STOP=1 -c "ALTER DATABASE ${ESC_POSTGRES_DB} OWNER TO ${ESC_POSTGRES_USER};"
  postgres_admin_exec -d postgres -v ON_ERROR_STOP=1 -c "GRANT ALL PRIVILEGES ON DATABASE ${ESC_POSTGRES_DB} TO ${ESC_POSTGRES_USER};"

  log "Seeding PostgreSQL sample schema/data..."
  PGPASSWORD="$POSTGRES_TEST_PASSWORD" psql \\
    -h "$POSTGRES_TEST_HOST" \\
    -p "$POSTGRES_TEST_PORT" \\
    -U "$POSTGRES_TEST_USER" \\
    -d "$POSTGRES_TEST_DB" \\
    -v ON_ERROR_STOP=1 \\
    -f "$REPO_ROOT/test_data/database/postgresql/create_schema_and_seed.sql"
fi

SCAN_CONFIG=""
SCAN_OUTPUT=""
SCAN_LABEL=""
if [ "$SKIP_MYSQL_TEST" = "0" ] && [ "$SKIP_POSTGRES_TEST" = "0" ]; then
  SCAN_CONFIG="$INTEGRATION_TEST_CONFIG"
  SCAN_OUTPUT="$INTEGRATION_TEST_OUTPUT"
  SCAN_LABEL="MySQL + PostgreSQL + filesystem"
elif [ "$SKIP_MYSQL_TEST" = "0" ]; then
  SCAN_CONFIG="$MYSQL_TEST_CONFIG"
  SCAN_OUTPUT="$MYSQL_TEST_OUTPUT"
  SCAN_LABEL="MySQL + filesystem"
elif [ "$SKIP_POSTGRES_TEST" = "0" ]; then
  SCAN_CONFIG="$POSTGRES_TEST_CONFIG"
  SCAN_OUTPUT="$POSTGRES_TEST_OUTPUT"
  SCAN_LABEL="PostgreSQL"
fi

if [ -n "$SCAN_CONFIG" ]; then
  log "Running ${SCAN_LABEL} integration test scan (packaged launcher)..."
  mkdir -p "$(dirname "$SCAN_OUTPUT")"
  (
    cd "$REPO_ROOT"
    DPDP_MYSQL_PASSWORD="$MYSQL_TEST_PASSWORD" \\
      DPDP_POSTGRES_PASSWORD="$POSTGRES_TEST_PASSWORD" \\
      ./dist/dpdp-pii-scanner/dpdp-scan \\
        --config "$SCAN_CONFIG" \\
        --output "$SCAN_OUTPUT"
  )

  log "Integration test report: $SCAN_OUTPUT"
fi

log "Build complete."
log "Activate venv: source $VENV_DIR/bin/activate"
log "Artifacts:"
log "  - $REPO_ROOT/dist/dpdp-pii-scanner"
log "  - $REPO_ROOT/dist/dpdp-pii-scanner-$(uname -s | tr '[:upper:]' '[:lower:]')-$(uname -m | tr '[:upper:]' '[:lower:]').zip"
if [ -n "$SCAN_OUTPUT" ]; then
  log "  - $SCAN_OUTPUT"
fi
