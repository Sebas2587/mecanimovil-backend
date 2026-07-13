#!/usr/bin/env bash
# Build para worker de scraping (Playwright + Chromium)
set -o errexit

echo "📦 Instalando dependencias..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🌐 Instalando Chromium para Playwright..."
python -m playwright install chromium --with-deps 2>/dev/null || python -m playwright install chromium

echo "✅ Build scraper worker completado"
