#!/usr/bin/env bash
# Build scraper worker: deps + Chromium en path persistido del proyecto (Render).
set -o errexit
set -o pipefail

echo "📦 Instalando dependencias Python..."
pip install --upgrade pip
pip install -r requirements.txt

# CRÍTICO: el cache en /opt/render/.cache NO se sube al runtime.
# Hay que instalar browsers dentro del project dir.
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/render/project/src/.playwright}"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"

echo "🌐 Instalando Chromium en $PLAYWRIGHT_BROWSERS_PATH ..."
# install-deps suele fallar sin root/apt en Render nativo — no es bloqueante.
python -m playwright install-deps chromium || echo "⚠️ install-deps omitido (sin apt)"

# Forzar descarga al path del proyecto (no al cache home).
python -m playwright install --force chromium

python - <<'PY'
import os
from pathlib import Path

browsers = Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]).expanduser()
print(f"PLAYWRIGHT_BROWSERS_PATH={browsers}")
found = list(browsers.rglob("chrome")) + list(browsers.rglob("headless_shell"))
print(f"Binarios: {len(found)}")
for p in found[:10]:
    print(" -", p)
if not found:
    raise SystemExit("Chromium no quedó en el project path — el scrape fallaría en runtime")

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    browser.close()
print("✅ Chromium lanza OK desde project path")
PY

echo "✅ Build scraper worker completado"
