#!/bin/bash
# Script para ver logs y estado desde SSH en Render
# Ejecuta estos comandos uno por uno en tu sesión SSH

echo "🔍 ========================================"
echo "🔍 VERIFICAR ESTADO Y LOGS DESDE SSH"
echo "🔍 ========================================"
echo ""
echo "⚠️  NOTA: El servidor YA está corriendo en Render"
echo "    NO necesitas ejecutarlo manualmente"
echo ""

# 1. Verificar que el servidor está corriendo
echo "1️⃣ Verificando procesos del servidor:"
echo "   Procesos Python/Django:"
ps aux | grep -E "python|daphne|gunicorn" | grep -v grep || echo "   ⚠️ No se encontraron procesos (puede estar en otro contenedor)"
echo ""

# 2. Ver puertos en uso
echo "2️⃣ Puertos en escucha:"
netstat -tulpn 2>/dev/null | grep LISTEN || lsof -i -P -n 2>/dev/null | grep LISTEN | head -5
echo ""

# 3. Ver variables de entorno
echo "3️⃣ Variables de entorno importantes:"
echo "   CPANEL_FTP_HOST: ${CPANEL_FTP_HOST:-❌ No definida}"
echo "   CPANEL_FTP_USER: ${CPANEL_FTP_USER:-❌ No definida}"
echo "   CPANEL_FTP_ROOT: ${CPANEL_FTP_ROOT:-❌ No definida}"
echo "   STORAGE_TYPE: ${STORAGE_TYPE:-❌ No definida}"
echo ""

# 4. Buscar archivos de log
echo "4️⃣ Buscando archivos de log:"
LOG_FILES=$(find /opt/render/project/src -name "*.log" -type f 2>/dev/null | head -5)
if [ -z "$LOG_FILES" ]; then
    echo "   ⚠️ No se encontraron archivos .log"
    echo "   💡 Los logs se ven mejor en Render Dashboard → Logs"
else
    echo "   ✅ Archivos de log encontrados:"
    echo "$LOG_FILES" | while read logfile; do
        echo "      - $logfile"
    done
    echo ""
    echo "   Para ver logs en tiempo real:"
    echo "   tail -f $LOG_FILES"
fi
echo ""

# 5. Ver logs del sistema (últimas líneas)
echo "5️⃣ Últimas líneas de logs del sistema (si disponibles):"
dmesg 2>/dev/null | tail -5 || echo "   ⚠️ No se puede acceder a dmesg"
echo ""

# 6. Verificar configuración Django
echo "6️⃣ Verificando configuración Django:"
cd /opt/render/project/src 2>/dev/null || cd /opt/render/project/*/src 2>/dev/null || {
    echo "   ⚠️ No se pudo encontrar el directorio del proyecto"
    echo "   Buscando manage.py..."
    PROJECT_DIR=$(find /opt -name "manage.py" -type f 2>/dev/null | head -1 | xargs dirname)
    if [ -n "$PROJECT_DIR" ]; then
        cd "$PROJECT_DIR"
        echo "   ✅ Proyecto encontrado en: $PROJECT_DIR"
    else
        echo "   ❌ No se encontró manage.py"
        exit 1
    fi
}

python3 manage.py check --deploy 2>&1 | head -10
echo ""

# 7. Verificar conexión a base de datos
echo "7️⃣ Verificando conexión a base de datos:"
python3 manage.py shell << 'PYTHON_EOF' 2>&1 | head -5
from django.db import connection
try:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        print("   ✅ Conexión a base de datos exitosa")
except Exception as e:
    print(f"   ❌ Error de conexión: {e}")
PYTHON_EOF
echo ""

# 8. Ver vehículos recientes
echo "8️⃣ Verificando vehículos en base de datos:"
python3 manage.py shell << 'PYTHON_EOF' 2>&1 | head -10
from apps.vehiculos.models import Vehiculo
total = Vehiculo.objects.count()
print(f"   📊 Total de vehículos: {total}")
if total > 0:
    print("   📋 Últimos 3 vehículos:")
    for v in Vehiculo.objects.order_by('-id')[:3]:
        foto = v.foto.name if v.foto else "Sin foto"
        print(f"      - Vehículo {v.id}: {foto}")
PYTHON_EOF
echo ""

# 9. Instrucciones para ver logs reales
echo "📋 ========================================"
echo "📋 CÓMO VER LOGS EN TIEMPO REAL"
echo "📋 ========================================"
echo ""
echo "✅ MEJOR OPCIÓN: Render Dashboard"
echo "   1. Ve a: https://dashboard.render.com"
echo "   2. Selecciona tu servicio"
echo "   3. Haz clic en 'Logs'"
echo "   4. Verás logs en tiempo real con filtros"
echo ""
echo "🔍 DESDE SSH (si hay archivos de log):"
if [ -n "$LOG_FILES" ]; then
    echo "   tail -f $LOG_FILES"
else
    echo "   Los logs se capturan en stdout/stderr"
    echo "   Render los muestra en el Dashboard"
fi
echo ""
echo "💡 Para ver logs específicos de tu aplicación:"
echo "   - Ve al Dashboard de Render"
echo "   - Filtra por nivel (WARNING, ERROR)"
echo "   - Busca términos como 'CPanelStorage', 'FTP', 'vehicle_'"
echo ""
