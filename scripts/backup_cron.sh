#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

bash "$APP_DIR/scripts/postgres_backup.sh"
