#!/usr/bin/env bash
# Arranque del worker scraper: asegura Chromium antes de Celery.
set -o errexit
set -o pipefail

export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/render/project/src/.playwright}"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"

need_install=0
if ! python - <<'PY'
import os
from pathlib import Path
from playwright.sync_api import sync_playwright
browsers = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")).expanduser()
found = list(browsers.rglob("chrome")) + list(browsers.rglob("headless_shell"))
if not found:
    raise SystemExit(1)
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    b.close()
PY
then
  need_install=1
fi

if [ "$need_install" = "1" ]; then
  echo "🌐 Chromium ausente en runtime — reinstalando en $PLAYWRIGHT_BROWSERS_PATH"
  python -m playwright install --force chromium
fi

exec celery -A mecanimovilapp worker -l info -Q scraper --concurrency=1 --pool=solo --max-tasks-per-child=10
