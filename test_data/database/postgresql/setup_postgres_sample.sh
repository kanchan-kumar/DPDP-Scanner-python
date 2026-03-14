#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SQL_FILE="$SCRIPT_DIR/create_schema_and_seed.sql"

PSQL_BIN="${PSQL_BIN:-psql}"

PGADMIN_USER="${PGADMIN_USER:-postgres}"
PGADMIN_PASSWORD="${PGADMIN_PASSWORD:-}"
PGADMIN_DB="${PGADMIN_DB:-postgres}"
PGADMIN_HOST="${PGADMIN_HOST:-127.0.0.1}"
PGADMIN_PORT="${PGADMIN_PORT:-5432}"
PGADMIN_USE_SUDO="${PGADMIN_USE_SUDO:-auto}"

PG_SAMPLE_DB="${PG_SAMPLE_DB:-dpdp_scanner_sample}"
PG_SAMPLE_USER="${PG_SAMPLE_USER:-dpdp_scanner}"
PG_SAMPLE_PASSWORD="${PG_SAMPLE_PASSWORD:-dpdp_scanner}"
PG_SAMPLE_HOST="${PG_SAMPLE_HOST:-127.0.0.1}"
PG_SAMPLE_PORT="${PG_SAMPLE_PORT:-5432}"

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

DB_EXISTS=$("${ADMIN_ENV[@]}" "${PSQL_ADMIN[@]}" "${ADMIN_ARGS[@]}" -tAc "SELECT 1 FROM pg_database WHERE datname = '${PG_SAMPLE_DB}'")
if [[ "$DB_EXISTS" != "1" ]]; then
  "${ADMIN_ENV[@]}" "${PSQL_ADMIN[@]}" "${ADMIN_ARGS[@]}" -c "CREATE DATABASE ${PG_SAMPLE_DB};"
fi

ROLE_EXISTS=$("${ADMIN_ENV[@]}" "${PSQL_ADMIN[@]}" "${ADMIN_ARGS[@]}" -tAc "SELECT 1 FROM pg_roles WHERE rolname = '${PG_SAMPLE_USER}'")
if [[ "$ROLE_EXISTS" != "1" ]]; then
  "${ADMIN_ENV[@]}" "${PSQL_ADMIN[@]}" "${ADMIN_ARGS[@]}" -c "CREATE USER ${PG_SAMPLE_USER} WITH PASSWORD '${PG_SAMPLE_PASSWORD}';"
fi

"${ADMIN_ENV[@]}" "${PSQL_ADMIN[@]}" "${ADMIN_ARGS[@]}" -c "ALTER DATABASE ${PG_SAMPLE_DB} OWNER TO ${PG_SAMPLE_USER};"
"${ADMIN_ENV[@]}" "${PSQL_ADMIN[@]}" "${ADMIN_ARGS[@]}" -c "GRANT ALL PRIVILEGES ON DATABASE ${PG_SAMPLE_DB} TO ${PG_SAMPLE_USER};"

PGPASSWORD="$PG_SAMPLE_PASSWORD" "$PSQL_BIN" \
  -h "$PG_SAMPLE_HOST" \
  -p "$PG_SAMPLE_PORT" \
  -U "$PG_SAMPLE_USER" \
  -d "$PG_SAMPLE_DB" \
  -v ON_ERROR_STOP=1 \
  -f "$SQL_FILE"

echo "PostgreSQL sample dataset ready: $PG_SAMPLE_DB"
