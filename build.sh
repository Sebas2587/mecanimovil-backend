#!/usr/bin/env bash
# Script de build para Render - MecaniMovil Backend
# Este script se ejecuta durante el deployment

set -o errexit  # Salir si hay errores

echo "📦 Instalando dependencias de Python..."
pip install --upgrade pip
pip install -r requirements.txt

echo "📁 Creando directorios necesarios..."
mkdir -p staticfiles
mkdir -p media

# Build no debe reutilizar conexiones largas; y necesita más paciencia con Postgres 256MB.
export CONN_MAX_AGE=0
export DB_CONNECT_TIMEOUT="${DB_CONNECT_TIMEOUT:-45}"

wait_for_db() {
  local max_attempts="${1:-18}"
  local sleep_secs="${2:-10}"
  local attempt=1
  echo "⏳ Esperando Postgres antes de migrar (hasta $((max_attempts * sleep_secs))s)..."
  while [ "$attempt" -le "$max_attempts" ]; do
    if python - <<'PY'
import os
import sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
import django
django.setup()
from django.db import connection
try:
    connection.close_if_unusable_or_obsolete()
    connection.ensure_connection()
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
        cursor.fetchone()
except Exception as exc:
    print(f'DB no lista: {type(exc).__name__}: {exc}', file=sys.stderr)
    sys.exit(1)
print('DB OK')
PY
    then
      echo "✅ Postgres disponible (intento $attempt/$max_attempts)"
      return 0
    fi
    echo "⚠️ Intento $attempt/$max_attempts falló; reintento en ${sleep_secs}s..."
    sleep "$sleep_secs"
    attempt=$((attempt + 1))
  done
  echo "❌ Postgres no respondió a tiempo (timeout de conexión / sobrecarga)."
  return 1
}

run_with_retries() {
  local label="$1"
  shift
  local max_attempts="${DB_CMD_RETRIES:-4}"
  local sleep_secs=8
  local attempt=1
  while [ "$attempt" -le "$max_attempts" ]; do
    echo "▶️  $label (intento $attempt/$max_attempts)"
    if "$@"; then
      return 0
    fi
    echo "⚠️ Falló: $label — reintento en ${sleep_secs}s"
    sleep "$sleep_secs"
    attempt=$((attempt + 1))
  done
  echo "❌ Agotados reintentos: $label"
  return 1
}

wait_for_db

echo "📊 Ejecutando migraciones de base de datos..."
run_with_retries "cleanup_ghost_rename_migrations" \
  python manage.py cleanup_ghost_rename_migrations
run_with_retries "migrate" \
  python manage.py migrate --noinput

echo "🔧 Inicializando sistema Smart Health..."
run_with_retries "init_smart_health" \
  python manage.py init_smart_health \
  || echo "⚠️ Advertencia: init_smart_health no completó, revisar logs"

echo "🧰 Sincronizando templates de checklist por servicio (idempotente)..."
run_with_retries "populate_checklists_por_servicio" \
  python manage.py populate_checklists_por_servicio \
  || echo "⚠️ Advertencia: populate_checklists_por_servicio no completó, revisar logs"

echo "🔄 Sincronizando ofertas marketplace estancadas en en_ejecucion (idempotente)..."
python manage.py sincronizar_cierre_marketplace_ordenes \
  || echo "⚠️ Advertencia: sincronizar_cierre_marketplace_ordenes no completó, revisar logs"

echo "🎨 Recolectando archivos estáticos..."
python manage.py collectstatic --noinput

echo "👤 Creando superusuario si no existe..."
python manage.py shell << EOF
from django.contrib.auth import get_user_model
import os

User = get_user_model()
username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@mecanimovil.com')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', None)

if password and not User.objects.filter(email=email).exists():
    print(f"Creando superusuario: {email}")
    User.objects.create_superuser(
        email=email,
        username=username,
        password=password,
        tipo_usuario='admin'
    )
    print("✅ Superusuario creado exitosamente")
else:
    print("ℹ️ Superusuario ya existe o no se proporcionó contraseña")
EOF

echo "💳 Asegurando planes de suscripción por nombre (solo crea faltantes; no pisa precios existentes)..."
python scripts/cargar_planes_suscripcion.py \
  || echo "⚠️ Advertencia: cargar_planes_suscripcion no completó, revisar logs"

echo "✅ Build completado exitosamente!"
