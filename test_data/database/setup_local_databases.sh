#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL=0
WITH_ENV=0
targets=()

usage() {
  cat <<'USAGE'
Usage: ./test_data/database/setup_local_databases.sh [options]

Options:
  --mysql           Set up the MySQL sample database.
  --postgres        Set up the PostgreSQL sample database.
  --all             Set up both MySQL and PostgreSQL (default).
  --install         Attempt to install database packages and start services.
  --with-env        Create the Python venv for DB scans (runs setup_piicatcher_env.sh).
  --skip-install    Do not attempt to install database packages (default).
  -h, --help        Show this help.

Examples:
  ./test_data/database/setup_local_databases.sh
  ./test_data/database/setup_local_databases.sh --mysql
  ./test_data/database/setup_local_databases.sh --postgres --with-env
  ./test_data/database/setup_local_databases.sh --all --install
USAGE
}

add_target() {
  local target="$1"
  for existing in "${targets[@]}"; do
    if [[ "$existing" == "$target" ]]; then
      return
    fi
  done
  targets+=("$target")
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mysql)
      add_target "mysql"
      ;;
    --postgres|--postgresql)
      add_target "postgres"
      ;;
    --all)
      targets=("mysql" "postgres")
      ;;
    --install)
      INSTALL=1
      ;;
    --skip-install)
      INSTALL=0
      ;;
    --with-env)
      WITH_ENV=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
 done

if [[ ${#targets[@]} -eq 0 ]]; then
  targets=("mysql" "postgres")
fi

install_mysql() {
  local os
  os="$(uname -s)"
  if [[ "$os" == "Darwin" ]]; then
    if ! command -v brew >/dev/null 2>&1; then
      echo "Homebrew not found. Install it or install MySQL manually." >&2
      return 1
    fi
    brew install mysql
    brew services start mysql
  elif [[ "$os" == "Linux" ]]; then
    if command -v apt-get >/dev/null 2>&1; then
      sudo apt-get update
      sudo apt-get install -y mysql-server
      sudo systemctl enable --now mysql
    else
      echo "Unsupported Linux package manager. Install MySQL manually." >&2
      return 1
    fi
  else
    echo "Unsupported OS for automatic MySQL install: $os" >&2
    return 1
  fi
}

install_postgres() {
  local os
  os="$(uname -s)"
  if [[ "$os" == "Darwin" ]]; then
    if ! command -v brew >/dev/null 2>&1; then
      echo "Homebrew not found. Install it or install PostgreSQL manually." >&2
      return 1
    fi
    brew install postgresql
    brew services start postgresql
  elif [[ "$os" == "Linux" ]]; then
    if command -v apt-get >/dev/null 2>&1; then
      sudo apt-get update
      sudo apt-get install -y postgresql postgresql-client
      sudo systemctl enable --now postgresql
    else
      echo "Unsupported Linux package manager. Install PostgreSQL manually." >&2
      return 1
    fi
  else
    echo "Unsupported OS for automatic PostgreSQL install: $os" >&2
    return 1
  fi
}

if [[ "$WITH_ENV" == "1" ]]; then
  "$SCRIPT_DIR/setup_piicatcher_env.sh"
fi

for target in "${targets[@]}"; do
  case "$target" in
    mysql)
      if [[ "$INSTALL" == "1" ]]; then
        install_mysql
      fi
      if ! command -v mysql >/dev/null 2>&1; then
        echo "mysql client not found. Install it or re-run with --install." >&2
        exit 1
      fi
      bash "$SCRIPT_DIR/mysql/setup_mysql_sample.sh"
      ;;
    postgres)
      if [[ "$INSTALL" == "1" ]]; then
        install_postgres
      fi
      if ! command -v psql >/dev/null 2>&1; then
        echo "psql client not found. Install it or re-run with --install." >&2
        exit 1
      fi
      bash "$SCRIPT_DIR/postgresql/setup_postgres_sample.sh"
      ;;
    *)
      echo "Unsupported target: $target" >&2
      exit 1
      ;;
  esac
 done
