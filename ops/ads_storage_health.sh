#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/www/wwwroot/bi.jiajieco.com"
DISK_USE_PERCENT="$(df -P / | awk 'NR==2 {gsub(/%/, "", $5); print $5}')"

cd "$APP_DIR"
docker compose exec -T backend python -m app.jobs.ads_retention \
  --health \
  --disk-use-percent "$DISK_USE_PERCENT" \
  "$@"
