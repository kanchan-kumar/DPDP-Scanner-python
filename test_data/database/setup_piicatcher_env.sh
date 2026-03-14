#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${DPDP_PYTHON_BIN:-python3.10}"
VENV_DIR="${DPDP_VENV_DIR:-.venv}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${DPDP_REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
REQUIREMENTS_FILE="$REPO_ROOT/requirements.txt"
PIICATCHER_INSTALL_SPEC="${PIICATCHER_INSTALL_SPEC:-git+https://github.com/tokern/piicatcher.git}"
DOWNLOAD_SPACY_MODEL="${DPDP_DOWNLOAD_SPACY_MODEL:-1}"
PIP_CHECK_STRICT="${DPDP_PIP_CHECK_STRICT:-0}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python binary not found: $PYTHON_BIN" >&2
  echo "Install Python 3.10 (required by piicatcher + scanner)." >&2
  exit 1
fi

# Hard fail unless interpreter is Python 3.10.x.
PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$PYTHON_VERSION" != "3.10" ]]; then
  echo "Unsupported Python version from $PYTHON_BIN: $PYTHON_VERSION" >&2
  echo "Use Python 3.10 exactly. Example:" >&2
  echo "  DPDP_PYTHON_BIN=python3.10 ./test_data/database/setup_piicatcher_env.sh" >&2
  exit 1
fi

"$PYTHON_BIN" -m venv --clear "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade "pip<26" "setuptools<81" wheel
"$VENV_DIR/bin/python" -m pip install --upgrade "poetry-core>=1.7,<3"

if [[ -f "$REQUIREMENTS_FILE" ]]; then
  TMP_REQ="$(mktemp)"
  # Install non-piicatcher dependencies first, then piicatcher with ignore-requires-python.
  grep -Ev '^[[:space:]]*piicatcher([[:space:]]|@|=|$)' "$REQUIREMENTS_FILE" > "$TMP_REQ" || true
  "$VENV_DIR/bin/python" -m pip install --no-build-isolation -r "$TMP_REQ"
  rm -f "$TMP_REQ"
  "$VENV_DIR/bin/python" -m pip install --no-build-isolation --prefer-binary --ignore-requires-python "piicatcher @ $PIICATCHER_INSTALL_SPEC"
else
  "$VENV_DIR/bin/python" -m pip install --no-build-isolation pymysql psycopg2-binary
  "$VENV_DIR/bin/python" -m pip install --no-build-isolation --prefer-binary --ignore-requires-python "piicatcher @ $PIICATCHER_INSTALL_SPEC"
fi

# Re-apply compatibility pins to keep one venv conflict-free with dbcat/piicatcher.
"$VENV_DIR/bin/python" -m pip install --no-build-isolation --upgrade \
  "presidio-analyzer>=2.2.0,<3" \
  "presidio-anonymizer>=2.2.0,<3" \
  "spacy>=3.4.4,<3.7" \
  "pydantic>=1.10.2,<2" \
  "thinc<8.2" \
  "typer>=0.4,<0.5" \
  "cryptography<46"

if ! "$VENV_DIR/bin/python" -m pip check; then
  if [[ "$PIP_CHECK_STRICT" == "1" ]]; then
    echo "pip check failed and strict mode is enabled (DPDP_PIP_CHECK_STRICT=1)." >&2
    exit 1
  fi
  echo "WARNING: pip check reported dependency conflicts; continuing (DPDP_PIP_CHECK_STRICT=0)." >&2
fi

if [[ "$DOWNLOAD_SPACY_MODEL" == "1" ]]; then
  "$VENV_DIR/bin/python" -m spacy download en_core_web_lg || true
fi

echo "Environment created at: $VENV_DIR"
echo "Activate with: source $VENV_DIR/bin/activate"
