#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/www/wwwroot/bi.jiajieco.com"

run_ads_build() {
  local label=$1
  shift

  for attempt in 1 2 3; do
    if "$@"; then
      return 0
    fi

    if [ "$attempt" -eq 3 ]; then
      echo "$label failed after 3 attempts." >&2
      return 1
    fi

    local delay=$((attempt * 10))
    echo "$label attempt $attempt failed; retrying in ${delay}s." >&2
    sleep "$delay"
  done
}

cd "$APP_DIR"
run_ads_build "Sales ADS build" \
  docker compose exec -T backend python -m app.jobs.build_sales_ads
run_ads_build "Inventory ADS build" \
  docker compose exec -T backend python -m app.jobs.build_inventory_ads
