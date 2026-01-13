#!/usr/bin/env python3
"""
Script para probar la subida de imágenes y ver logs detallados desde SSH en Render.
Ejecuta: python3 scripts/test_upload_imagen.py
"""

import os
import sys
import django
import logging
import tempfile
from io import BytesIO

# Configurar logging para ver TODO
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Agregar el directorio del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mecanimovilapp.settings')
django.setup()

from django.conf import settings
from mecanimovilapp.storage.cpanel_storage import CPanelStorage
from apps.vehiculos.models import Vehiculo

print("=" * 80)
print("🔍 DIAGNÓSTICO DE SUBIDA DE IMÁGENES - LOGS DETALLADOS")
print("=" * 80)
print()

# 1. Verificar configuración
print("1️⃣ CONFIGURACIÓN:")
print("-" * 80)
print(f"   STORAGE_TYPE: {getattr(settings, 'STORAGE_TYPE', 'No definido')}")
print(f"   DEFAULT_FILE_STORAGE: {getattr(settings, 'DEFAULT_FILE_STORAGE', 'No definido')}")
print(f"   CPANEL_FTP_HOST: {getattr(settings, 'CPANEL_FTP_HOST', 'No definido')}")
print(f"   CPANEL_FTP_USER: {getattr(settings, 'CPANEL_FTP_USER', 'No definido')}")
print(f"   CPANEL_FTP_ROOT: {getattr(settings, 'CPANEL_FTP_ROOT', 'No definido')}")
print(f"   CPANEL_MEDIA_URL: {getattr(settings, 'CPANEL_MEDIA_URL', 'No definido')}")
print()

# 2. Verificar variables de entorno
print("2️⃣ VARIABLES DE ENTORNO:")
print("-" * 80)
print(f"   CPANEL_FTP_HOST: {os.getenv('CPANEL_FTP_HOST', '❌ No definida')}")
print(f"   CPANEL_FTP_USER: {os.getenv('CPANEL_FTP_USER', '❌ No definida')}")
print(f"   CPANEL_FTP_PASSWORD: {'✅ Definida' if os.getenv('CPANEL_FTP_PASSWORD') else '❌ No definida'}")
print(f"   CPANEL_FTP_ROOT: {os.getenv('CPANEL_FTP_ROOT', '❌ No definida')}")
print(f"   CPANEL_MEDIA_URL: {os.getenv('CPANEL_MEDIA_URL', '❌ No definida')}")
print(f"   STORAGE_TYPE: {os.getenv('STORAGE_TYPE', '❌ No definida')}")
print()

# 3. Probar conexión FTP
print("3️⃣ PROBANDO CONEXIÓN FTP:")
print("-" * 80)
try:
    import ftplib
    ftp_host = os.getenv('CPANEL_FTP_HOST')
    ftp_user = os.getenv('CPANEL_FTP_USER')
    ftp_pass = os.getenv('CPANEL_FTP_PASSWORD')
    
    if not all([ftp_host, ftp_user, ftp_pass]):
        print("   ❌ Faltan credenciales FTP")
    else:
        print(f"   🔄 Conectando a {ftp_host}...")
        ftp = ftplib.FTP(ftp_host)
        ftp.set_debuglevel(2)  # Ver comandos FTP
        ftp.login(ftp_user, ftp_pass)
        ftp.set_pasv(True)
        
        current_dir = ftp.pwd()
        print(f"   ✅ Conexión FTP exitosa")
        print(f"   📁 Directorio actual: {current_dir}")
        
        # Intentar navegar al directorio de destino
        ftp_root = os.getenv('CPANEL_FTP_ROOT', '')
        if ftp_root:
            print(f"   🔄 Intentando navegar a: {ftp_root}")
            # Dividir la ruta
            parts = ftp_root.replace('public_html/', '').split('/')
            parts = [p for p in parts if p]
            
            # Navegar a public_html si existe
            try:
                ftp.cwd('public_html')
                print(f"   ✅ Navegado a public_html/")
            except:
                print(f"   ⚠️ No se pudo navegar a public_html/")
            
            # Navegar por cada parte
            for part in parts:
                try:
                    ftp.cwd(part)
                    print(f"   ✅ Navegado a {part}/")
                except ftplib.error_perm as e:
                    print(f"   ⚠️ Directorio {part} no existe: {e}")
                    try:
                        ftp.mkd(part)
                        print(f"   ✅ Directorio {part} creado")
                        ftp.cwd(part)
                    except Exception as e2:
                        print(f"   ❌ Error creando directorio {part}: {e2}")
                        break
            
            final_dir = ftp.pwd()
            print(f"   📁 Directorio final: {final_dir}")
            
            # Listar archivos
            files = ftp.nlst()
            print(f"   📄 Archivos en directorio ({len(files)} encontrados):")
            for f in files[:10]:
                if f not in ['.', '..']:
                    print(f"      - {f}")
            if len(files) > 10:
                print(f"      ... y {len(files) - 10} más")
        
        ftp.quit()
        print("   ✅ Conexión FTP cerrada")
except Exception as e:
    print(f"   ❌ Error en conexión FTP: {e}")
    import traceback
    traceback.print_exc()
print()

# 4. Probar storage backend
print("4️⃣ PROBANDO STORAGE BACKEND:")
print("-" * 80)
try:
    storage = CPanelStorage()
    print(f"   ✅ Storage inicializado")
    print(f"   📁 Location: {storage.location}")
    print(f"   🌐 Base URL: {storage.base_url}")
    
    # Crear un archivo de prueba
    test_content = b"Test image content for debugging"
    test_file = BytesIO(test_content)
    test_file.name = "test_upload_debug.jpg"
    
    print(f"   🔄 Intentando subir archivo de prueba: {test_file.name}")
    saved_name = storage.save(test_file.name, test_file)
    print(f"   ✅ Archivo guardado como: {saved_name}")
    
    # Verificar URL
    url = storage.url(saved_name)
    print(f"   🌐 URL generada: {url}")
    
except Exception as e:
    print(f"   ❌ Error en storage backend: {e}")
    import traceback
    traceback.print_exc()
print()

# 5. Verificar vehículos existentes
print("5️⃣ VEHÍCULOS EN BASE DE DATOS:")
print("-" * 80)
try:
    vehiculos = Vehiculo.objects.all()[:5]
    total = Vehiculo.objects.count()
    print(f"   📊 Total de vehículos: {total}")
    print(f"   📋 Últimos 5 vehículos:")
    for v in vehiculos:
        foto_info = f"Foto: {v.foto.name}" if v.foto else "Sin foto"
        foto_url = v.foto.url if v.foto else "N/A"
        print(f"      - Vehículo {v.id}: {foto_info}")
        if v.foto:
            print(f"        URL: {foto_url}")
            print(f"        Storage: {type(v.foto.storage).__name__}")
except Exception as e:
    print(f"   ❌ Error consultando vehículos: {e}")
    import traceback
    traceback.print_exc()
print()

print("=" * 80)
print("✅ Diagnóstico completado")
print("=" * 80)
