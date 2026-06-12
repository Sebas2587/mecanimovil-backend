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

echo "📊 Ejecutando migraciones de base de datos..."
python manage.py migrate --noinput
echo "🔧 Inicializando sistema Smart Health..."
python manage.py init_smart_health

echo "🧰 Sincronizando templates de checklist por servicio (idempotente)..."
python manage.py populate_checklists_por_servicio

echo "🔁 Corrección puntual: oferta cerrada sin checklist (si aplica)..."
python manage.py revertir_oferta_cerrada_prematura \
  --oferta-id 2ec78118-5cdd-4cf1-aeef-ef8148c5a066 \
  || echo "ℹ️ Sin corrección necesaria para la oferta puntual"

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
python scripts/cargar_planes_suscripcion.py

echo "✅ Build completado exitosamente!"
