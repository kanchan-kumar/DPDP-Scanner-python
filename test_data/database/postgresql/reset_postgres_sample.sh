#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DROP_SQL="$SCRIPT_DIR/drop_schema.sql"
SETUP_SCRIPT="$SCRIPT_DIR/setup_postgres_sample.sh"

PSQL_BIN="${PSQL_BIN:-psql}"

PGADMIN_USER="${PGADMIN_USER:-postgres}"
PGADMIN_PASSWORD="${PGADMIN_PASSWORD:-}"
PGADMIN_DB="${PGADMIN_DB:-postgres}"
PGADMIN_HOST="${PGADMIN_HOST:-127.0.0.1}"
PGADMIN_PORT="${PGADMIN_PORT:-5432}"
PGADMIN_USE_SUDO="${PGADMIN_USE_SUDO:-auto}"

if ! command -v "$PSQL_BIN" >/dev/null 2>&1; then
  echo "psql client not found: $PSQL_BIN" >&2
  exit 1
fi

use_sudo=0
if [[ "$PGADMIN_USE_SUDO" == "1" ]]; then
  use_sudo=1
elif [[ "$PGADMIN_USE_SUDO" == "auto" ]]; then
  if [[ -z "$PGADMIN_PASSWORD" && "$PGADMIN_USER" == "postgres" ]] && command -v sudo >/dev/null 2>&1; then
    use_sudo=1
  fi
fi

PSQL_ADMIN=("$PSQL_BIN")
ADMIN_ARGS=("-d" "$PGADMIN_DB")
ADMIN_ENV=()

if [[ "$use_sudo" == "1" ]]; then
  PSQL_ADMIN=(sudo -u postgres "$PSQL_BIN")
else
  ADMIN_ARGS+=("-h" "$PGADMIN_HOST" "-p" "$PGADMIN_PORT" "-U" "$PGADMIN_USER")
  if [[ -n "$PGADMIN_PASSWORD" ]]; then
    ADMIN_ENV=("PGPASSWORD=$PGADMIN_PASSWORD")
  fi
fi

"${ADMIN_ENV[@]}" "${PSQL_ADMIN[@]}" "${ADMIN_ARGS[@]}" -v ON_ERROR_STOP=1 -f "$DROP_SQL"
"$SETUP_SCRIPT"

echo "PostgreSQL sample dataset reset complete."
