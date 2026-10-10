#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$APP_DIR/backups/postgres"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR"

export PGHOST="${PGHOST:-127.0.0.1}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-postgres}"
export PGPASSWORD="${PGPASSWORD:-}"
export PGDATABASE="${PGDATABASE:-${DB_NAME:-smartcampus}}"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL not set. Falling back to PG* environment values."
fi

if [[ -n "${DATABASE_URL:-}" ]]; then
  PYTHON_CODE=$(cat <<'PY'
import os, sys, urllib.parse
url = sys.argv[1]
parsed = urllib.parse.urlparse(url)
if parsed.scheme not in {"postgres", "postgresql"}:
    raise SystemExit("Unsupported DATABASE_URL scheme")
print(parsed.hostname or "127.0.0.1")
print(parsed.username or "postgres")
print(parsed.password or "")
print(parsed.path.lstrip("/"))
print(str(parsed.port or 5432))
PY
)
  readarray -t DB_INFO < <(python3 - "$DATABASE_URL" <<<"$PYTHON_CODE")
  if [[ ${#DB_INFO[@]} -ge 4 ]]; then
    export PGHOST="${DB_INFO[0]}"
    export PGUSER="${DB_INFO[1]}"
    export PGPASSWORD="${DB_INFO[2]}"
    export PGDATABASE="${DB_INFO[3]}"
    export PGPORT="${DB_INFO[4]:-5432}"
  fi
fi

if [[ -z "${PGDATABASE}" || -z "${PGUSER}" ]]; then
  echo "Unable to resolve PostgreSQL database credentials. Check DATABASE_URL or PG* variables."
  exit 1
fi

BACKUP_FILE="$BACKUP_DIR/${PGDATABASE}_${TIMESTAMP}.dump"
pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -Fc -f "$BACKUP_FILE"

find "$BACKUP_DIR" -type f -name '*.dump' -mtime +"$RETENTION_DAYS" -delete

printf 'PostgreSQL backup created: %s\n' "$BACKUP_FILE"
