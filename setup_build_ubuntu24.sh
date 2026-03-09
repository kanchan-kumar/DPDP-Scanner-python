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
# 8) Installs/configures MySQL sample data and runs scanner test
#    using run_scanner_mysql_and_files.json (patched runtime copy)
#
# Usage:
#   ./setup_build_ubuntu24.sh
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
#   DPDP_SKIP_MYSQL_TEST=0|1
#   DPDP_MYSQL_TEST_HOST=127.0.0.1
#   DPDP_MYSQL_TEST_PORT=3306
#   DPDP_MYSQL_TEST_USER=dpdp_scanner
#   DPDP_MYSQL_TEST_PASSWORD=dpdp_scanner
#   DPDP_MYSQL_TEST_CONFIG=run_scanner_mysql_and_files.json
#   DPDP_MYSQL_TEST_OUTPUT=output/run_scanner_mysql_and_files_report.json

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

mysql_root_exec() {
  if [ -n "${SUDO:-}" ]; then
    $SUDO mysql "$@"
  else
    mysql "$@"
  fi
}

REPO_ROOT="${DPDP_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
VENV_DIR="${DPDP_VENV_DIR:-$REPO_ROOT/.venv}"
PYTHON_BIN="${DPDP_PYTHON_BIN:-python3.10}"
DBCAT_INSTALL_SPEC="${DPDP_DBCAT_INSTALL_SPEC:-dbcat==0.14.2}"
PIICATCHER_INSTALL_SPEC="${DPDP_PIICATCHER_INSTALL_SPEC:-git+https://github.com/tokern/piicatcher.git}"
SPACY_MODEL="${DPDP_SPACY_MODEL:-en_core_web_lg}"
SKIP_SYSTEM_DEPS="${DPDP_SKIP_SYSTEM_DEPS:-0}"
SKIP_SPACY_MODEL="${DPDP_SKIP_SPACY_MODEL:-0}"
SKIP_MYSQL_TEST="${DPDP_SKIP_MYSQL_TEST:-0}"
MYSQL_TEST_HOST="${DPDP_MYSQL_TEST_HOST:-127.0.0.1}"
MYSQL_TEST_PORT="${DPDP_MYSQL_TEST_PORT:-3306}"
MYSQL_TEST_USER="${DPDP_MYSQL_TEST_USER:-dpdp_scanner}"
MYSQL_TEST_PASSWORD="${DPDP_MYSQL_TEST_PASSWORD:-dpdp_scanner}"
MYSQL_TEST_CONFIG="${DPDP_MYSQL_TEST_CONFIG:-$REPO_ROOT/run_scanner_mysql_and_files.json}"
MYSQL_TEST_OUTPUT="${DPDP_MYSQL_TEST_OUTPUT:-$REPO_ROOT/output/run_scanner_mysql_and_files_report.json}"
MYSQL_RUNTIME_CONFIG="$REPO_ROOT/output/run_scanner_mysql_and_files.runtime.json"

[ -f "$REPO_ROOT/build_executable.py" ] || die "build_executable.py not found under REPO_ROOT=$REPO_ROOT"
[ -f "$REPO_ROOT/requirements.txt" ] || die "requirements.txt not found under REPO_ROOT=$REPO_ROOT"
if [ "$SKIP_MYSQL_TEST" = "0" ]; then
  [ -f "$MYSQL_TEST_CONFIG" ] || die "MySQL test config not found: $MYSQL_TEST_CONFIG"
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
  $SUDO apt-get update -y
  $SUDO apt-get install -y \
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
    default-libmysqlclient-dev \
    mysql-server \
    mysql-client \
    tesseract-ocr
fi

if ! command_exists python3.10; then
  if [ "$SKIP_SYSTEM_DEPS" = "1" ]; then
    die "python3.10 not found and DPDP_SKIP_SYSTEM_DEPS=1; install python3.10 manually."
  fi
  log "python3.10 not found. Adding deadsnakes PPA..."
  $SUDO add-apt-repository -y ppa:deadsnakes/ppa
  $SUDO apt-get update -y
  if ! $SUDO apt-get install -y python3.10 python3.10-venv python3.10-dev python3.10-distutils; then
    log "python3.10-distutils not available; retrying without it..."
    $SUDO apt-get install -y python3.10 python3.10-venv python3.10-dev
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

  log "Preparing runtime test config from run_scanner_mysql_and_files.json..."
  "$VENV_PY" - <<PY
import json
from pathlib import Path
from urllib.parse import quote

base_cfg = Path(r"$MYSQL_TEST_CONFIG")
runtime_cfg = Path(r"$MYSQL_RUNTIME_CONFIG")
output_file = Path(r"$MYSQL_TEST_OUTPUT")
host = r"$MYSQL_TEST_HOST"
port = int(r"$MYSQL_TEST_PORT")
user = r"$MYSQL_TEST_USER"
password = r"$MYSQL_TEST_PASSWORD"

data = json.loads(base_cfg.read_text(encoding="utf-8"))
sources = data.setdefault("sources", {})
sources["enabled_sources"] = ["filesystem", "database"]
sources.setdefault("database", {})["enabled"] = True

for conn in sources.get("database", {}).get("connections", []) or []:
    if str(conn.get("name", "")).strip() != "mysql_local_sample":
        conn["enabled"] = False
        continue

    conn["enabled"] = True
    conn["type"] = "mysql"
    conn["url"] = (
        f"mysql://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/dpdp_scanner_sample"
    )
    auth = conn.setdefault("auth", {})
    auth["username"] = user
    auth["password"] = ""
    auth["password_env"] = "DPDP_MYSQL_PASSWORD"

    piicatcher_cfg = conn.setdefault("piicatcher", {})
    piicatcher_cfg["enabled"] = True
    piicatcher_cfg["source_type"] = "mysql"
    piicatcher_cfg["source_name"] = "mysql_local_sample"
    piicatcher_cfg["source_kwargs"] = {
        "uri": host,
        "port": port,
        "username": user,
        "password": password,
        "database": "dpdp_scanner_sample",
    }

output_cfg = data.setdefault("output", {})
output_cfg["path"] = str(output_file)

runtime_cfg.parent.mkdir(parents=True, exist_ok=True)
runtime_cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
print(runtime_cfg)
PY

  log "Running MySQL + filesystem integration test scan..."
  mkdir -p "$(dirname "$MYSQL_TEST_OUTPUT")"
  DPDP_MYSQL_PASSWORD="$MYSQL_TEST_PASSWORD" \
    "$VENV_PY" "$REPO_ROOT/main.py" \
      --config "$MYSQL_RUNTIME_CONFIG" \
      --output "$MYSQL_TEST_OUTPUT" \
      --log-level INFO

  log "MySQL integration test report: $MYSQL_TEST_OUTPUT"
fi

log "Build complete."
log "Activate venv: source $VENV_DIR/bin/activate"
log "Artifacts:"
log "  - $REPO_ROOT/dist/dpdp-pii-scanner"
log "  - $REPO_ROOT/dist/dpdp-pii-scanner-$(uname -s | tr '[:upper:]' '[:lower:]')-$(uname -m | tr '[:upper:]' '[:lower:]').zip"
if [ "$SKIP_MYSQL_TEST" = "0" ]; then
  log "  - $MYSQL_RUNTIME_CONFIG"
  log "  - $MYSQL_TEST_OUTPUT"
fi
