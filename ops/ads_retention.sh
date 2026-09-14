#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/www/wwwroot/bi.jiajieco.com"
LOCK_FILE="/var/lock/bi-sales-ads.lock"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "ADS build or retention is already running; skip retention." >&2
  exit 75
fi

if pgrep -af 'app.jobs.build_(sales|inventory)_ads|refresh_sales_ads' >/dev/null; then
  echo "ADS build process detected; abort retention." >&2
  exit 75
fi

cd "$APP_DIR"
docker compose exec -T backend python -m app.jobs.ads_retention "$@"
