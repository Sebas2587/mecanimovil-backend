#!/bin/bash
# Script de diagnóstico para ejecutar desde SSH en Render
# Uso: Copia y pega estos comandos uno por uno en tu sesión SSH de Render

echo "🔍 ========================================"
echo "🔍 DIAGNÓSTICO DE CONFIGURACIÓN EN RENDER"
echo "🔍 ========================================"
echo ""

# 1. Verificar directorio actual
echo "1️⃣ Directorio actual:"
pwd
echo ""

# 2. Buscar el proyecto Django
echo "2️⃣ Buscando proyecto Django..."
if [ -f "/opt/render/project/src/manage.py" ]; then
    echo "✅ Proyecto encontrado en: /opt/render/project/src"
    cd /opt/render/project/src
elif [ -f "./manage.py" ]; then
    echo "✅ Proyecto encontrado en directorio actual"
else
    echo "⚠️ Buscando manage.py..."
    find /opt -name "manage.py" -type f 2>/dev/null | head -1
    if [ $? -eq 0 ]; then
        PROJECT_DIR=$(find /opt -name "manage.py" -type f 2>/dev/null | head -1 | xargs dirname)
        echo "✅ Proyecto encontrado en: $PROJECT_DIR"
        cd "$PROJECT_DIR"
    else
        echo "❌ No se encontró manage.py"
        exit 1
    fi
fi
echo ""

# 3. Verificar variables de entorno de cPanel
echo "3️⃣ Variables de entorno de cPanel:"
echo "   CPANEL_FTP_HOST: ${CPANEL_FTP_HOST:-❌ No definida}"
echo "   CPANEL_FTP_USER: ${CPANEL_FTP_USER:-❌ No definida}"
echo "   CPANEL_FTP_ROOT: ${CPANEL_FTP_ROOT:-❌ No definida}"
echo "   CPANEL_MEDIA_URL: ${CPANEL_MEDIA_URL:-❌ No definida}"
echo "   STORAGE_TYPE: ${STORAGE_TYPE:-❌ No definida}"
echo "   DEFAULT_FILE_STORAGE: ${DEFAULT_FILE_STORAGE:-❌ No definida}"
echo ""

# 4. Verificar configuración Django
echo "4️⃣ Verificando configuración Django:"
python3 manage.py shell << 'PYTHON_EOF'
from django.conf import settings
import os

print("   STORAGE_TYPE:", getattr(settings, 'STORAGE_TYPE', 'No definido'))
print("   DEFAULT_FILE_STORAGE:", getattr(settings, 'DEFAULT_FILE_STORAGE', 'No definido'))
print("   CPANEL_FTP_HOST:", getattr(settings, 'CPANEL_FTP_HOST', 'No definido'))
print("   CPANEL_FTP_USER:", getattr(settings, 'CPANEL_FTP_USER', 'No definido'))
print("   CPANEL_FTP_ROOT:", getattr(settings, 'CPANEL_FTP_ROOT', 'No definido'))
print("   CPANEL_MEDIA_URL:", getattr(settings, 'CPANEL_MEDIA_URL', 'No definido'))
PYTHON_EOF
echo ""

# 5. Probar conexión FTP
echo "5️⃣ Probando conexión FTP:"
python3 << 'PYTHON_EOF'
import ftplib
import os
import sys

ftp_host = os.getenv('CPANEL_FTP_HOST')
ftp_user = os.getenv('CPANEL_FTP_USER')
ftp_pass = os.getenv('CPANEL_FTP_PASSWORD')
ftp_root = os.getenv('CPANEL_FTP_ROOT', '')

if not all([ftp_host, ftp_user, ftp_pass]):
    print("   ❌ Faltan variables de entorno para FTP")
    sys.exit(1)

try:
    print(f"   🔄 Conectando a {ftp_host}...")
    ftp = ftplib.FTP(ftp_host)
    ftp.login(ftp_user, ftp_pass)
    ftp.set_pasv(True)
    
    current_dir = ftp.pwd()
    print(f"   ✅ Conexión FTP exitosa")
    print(f"   📁 Directorio actual FTP: {current_dir}")
    
    # Intentar navegar al directorio de destino
    if ftp_root:
        print(f"   🔄 Intentando navegar a: {ftp_root}")
        try:
            # Dividir la ruta y navegar paso a paso
            parts = ftp_root.replace('public_html/', '').split('/')
            parts = [p for p in parts if p]
            
            # Navegar a public_html si existe
            try:
                ftp.cwd('public_html')
                print(f"   ✅ Navegado a public_html/")
            except:
                pass
            
            # Navegar por cada parte
            for part in parts:
                try:
                    ftp.cwd(part)
                    print(f"   ✅ Navegado a {part}/")
                except ftplib.error_perm:
                    print(f"   ⚠️ Directorio {part} no existe")
                    break
            
            final_dir = ftp.pwd()
            print(f"   📁 Directorio final: {final_dir}")
            
            # Listar archivos
            files = ftp.nlst()
            print(f"   📄 Archivos en directorio ({len(files)} encontrados):")
            for f in files[:10]:  # Mostrar primeros 10
                if f not in ['.', '..']:
                    print(f"      - {f}")
            if len(files) > 10:
                print(f"      ... y {len(files) - 10} más")
        except Exception as e:
            print(f"   ⚠️ Error navegando: {e}")
    
    ftp.quit()
    print("   ✅ Conexión FTP cerrada correctamente")
    
except Exception as e:
    print(f"   ❌ Error en conexión FTP: {e}")
    import traceback
    traceback.print_exc()
PYTHON_EOF
echo ""

# 6. Verificar archivos de storage
echo "6️⃣ Verificando código de storage:"
if [ -f "mecanimovilapp/storage/cpanel_storage.py" ]; then
    echo "   ✅ cpanel_storage.py existe"
    echo "   📄 Últimas líneas del archivo:"
    tail -20 mecanimovilapp/storage/cpanel_storage.py | grep -E "(def _save|def _connect|location|remote_path)" | head -5
else
    echo "   ❌ cpanel_storage.py no encontrado"
fi
echo ""

# 7. Verificar vehículos en base de datos
echo "7️⃣ Verificando vehículos en base de datos:"
python3 manage.py shell << 'PYTHON_EOF'
from apps.vehiculos.models import Vehiculo

vehiculos = Vehiculo.objects.all()[:5]
print(f"   📊 Total de vehículos: {Vehiculo.objects.count()}")
print(f"   📋 Primeros 5 vehículos:")
for v in vehiculos:
    foto_info = f"Foto: {v.foto.name}" if v.foto else "Sin foto"
    print(f"      - Vehículo {v.id}: {foto_info}")
PYTHON_EOF
echo ""

echo "✅ Diagnóstico completado"
echo ""
echo "💡 Próximos pasos:"
echo "   1. Si hay errores en FTP, verifica las variables de entorno en Render Dashboard"
echo "   2. Si el directorio no existe, créalo manualmente en cPanel"
echo "   3. Revisa los logs del servicio para ver errores detallados"
