#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DROP_SQL="$SCRIPT_DIR/drop_schema.sql"
SETUP_SCRIPT="$SCRIPT_DIR/setup_mysql_sample.sh"

MYSQL_BIN="${MYSQL_BIN:-mysql}"
MYSQL_HOST="${MYSQL_HOST:-localhost}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:-root}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-}"

if ! command -v "$MYSQL_BIN" >/dev/null 2>&1; then
  echo "mysql client not found: $MYSQL_BIN" >&2
  exit 1
fi

MYSQL_ARGS=(
  "-h" "$MYSQL_HOST"
  "-P" "$MYSQL_PORT"
  "-u" "$MYSQL_USER"
)

if [[ -n "$MYSQL_PASSWORD" ]]; then
  MYSQL_ARGS+=("-p$MYSQL_PASSWORD")
fi

"$MYSQL_BIN" "${MYSQL_ARGS[@]}" < "$DROP_SQL"
"$SETUP_SCRIPT"

echo "MySQL sample dataset reset complete."
