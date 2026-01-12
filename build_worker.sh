#!/usr/bin/env bash
# Script de build para Workers de Celery en Render
# Más ligero que build.sh - solo instala dependencias

set -o errexit  # Salir si hay errores

echo "📦 Instalando dependencias de Python..."
pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Build del worker completado exitosamente!"
