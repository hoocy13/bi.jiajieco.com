#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/www/wwwroot/bi.jiajieco.com"

cd "$APP_DIR"
docker compose exec -T backend python -m app.jobs.build_sales_ads
docker compose exec -T backend python -m app.jobs.build_inventory_ads
