# 📋 Ver Logs desde SSH en Render

## ⚠️ Importante: El Servidor YA Está Corriendo

**NO necesitas ejecutar el servidor manualmente**. Render ya lo está ejecutando como servicio.

Si intentas ejecutar `python manage.py runserver` desde SSH:
- ❌ Creará conflictos de puertos
- ❌ No verás los logs reales del servicio
- ❌ Puede causar problemas

---

## ✅ Formas de Ver Logs

### Opción 1: Dashboard de Render (Recomendado) ⭐

**La mejor forma de ver logs en tiempo real:**

1. Ve a Render Dashboard
2. Selecciona tu servicio (`mecanimovil-api`)
3. Haz clic en **"Logs"** (barra lateral)
4. Verás los logs en tiempo real con:
   - ✅ Timestamps
   - ✅ Niveles (INFO, WARNING, ERROR)
   - ✅ Filtros
   - ✅ Búsqueda

**Ventajas:**
- Logs en tiempo real
- Fácil de filtrar y buscar
- No consume recursos SSH
- Historial completo

---

### Opción 2: Ver Logs desde SSH (Si Existen Archivos de Log)

Si tu aplicación guarda logs en archivos, puedes verlos:

```bash
# Conectarte a Render
ssh srv-abc123@ssh.oregon.render.com

# Buscar archivos de log
find /opt/render/project/src -name "*.log" -type f

# Ver logs en tiempo real (si existen)
tail -f /opt/render/project/src/logs/*.log

# Ver últimas 100 líneas
tail -n 100 /opt/render/project/src/logs/*.log

# Buscar errores
grep -i error /opt/render/project/src/logs/*.log
```

**Nota:** La mayoría de aplicaciones Django en Render no guardan logs en archivos, sino que los envían directamente a stdout/stderr, que Render captura y muestra en el Dashboard.

---

### Opción 3: Verificar Estado del Servidor desde SSH

```bash
# Ver procesos corriendo
ps aux | grep python
ps aux | grep daphne
ps aux | grep gunicorn

# Ver qué puerto está usando
netstat -tulpn | grep python
# O
lsof -i -P -n | grep LISTEN

# Ver variables de entorno del proceso
ps eww -p $(pgrep -f "daphne\|gunicorn\|runserver") | grep -E "CPANEL|DATABASE"
```

---

### Opción 4: Ejecutar Comandos Django (Sin Iniciar Servidor)

Puedes ejecutar comandos Django que generan output:

```bash
cd /opt/render/project/src

# Verificar configuración (genera output)
python3 manage.py check --deploy

# Ver migraciones (genera output)
python3 manage.py showmigrations

# Django shell (interactivo)
python3 manage.py shell

# Verificar modelos
python3 manage.py shell << 'EOF'
from apps.vehiculos.models import Vehiculo
print(f"Total vehículos: {Vehiculo.objects.count()}")
for v in Vehiculo.objects.all()[:5]:
    print(f"Vehículo {v.id}: {v.foto.name if v.foto else 'Sin foto'}")
EOF
```

---

## 🔍 Ver Logs Específicos de tu Aplicación

### Ver Logs de Django

Si tu aplicación usa `logging` y guarda en archivos:

```bash
# Buscar archivos de log de Django
find /opt/render/project/src -name "*.log" -o -name "django.log" -o -name "app.log"

# Ver logs de Django (si existen)
tail -f /opt/render/project/src/logs/django.log
```

### Ver Logs del Sistema

```bash
# Ver logs del sistema (si tienes acceso)
journalctl -u render-service  # Puede no estar disponible

# Ver logs de Docker (si aplica)
docker logs <container_id>  # Si usas Docker
```

---

## 🎯 Para tu Caso: Ver Logs de Subida de Imágenes

### Desde Dashboard (Mejor Opción)

1. Ve a Render Dashboard → Tu servicio → **Logs**
2. Filtra por "WARNING" o "ERROR"
3. Busca términos como:
   - `CPanelStorage`
   - `_save`
   - `FTP`
   - `vehicle_`

### Desde SSH (Verificar Estado)

```bash
# Conectarte
ssh srv-abc123@ssh.oregon.render.com

# Verificar que el servidor está corriendo
ps aux | grep -E "daphne|gunicorn|python.*manage.py"

# Verificar variables de entorno
env | grep CPANEL

# Probar conexión FTP (esto generará logs si hay errores)
python3 << 'EOF'
import ftplib
import os
import logging

# Configurar logging para ver errores
logging.basicConfig(level=logging.DEBUG)

try:
    ftp = ftplib.FTP(os.getenv('CPANEL_FTP_HOST'))
    ftp.login(os.getenv('CPANEL_FTP_USER'), os.getenv('CPANEL_FTP_PASSWORD'))
    print("✅ Conexión FTP exitosa")
    print("Directorio:", ftp.pwd())
    ftp.quit()
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
EOF
```

---

## 📊 Monitoreo en Tiempo Real

### Ver Requests HTTP en Tiempo Real

Los logs del Dashboard muestran todos los requests. Para verlos desde SSH (si hay archivos de acceso):

```bash
# Ver logs de acceso (si existen)
tail -f /opt/render/project/src/logs/access.log

# Ver solo errores
tail -f /opt/render/project/src/logs/error.log | grep -i error
```

---

## 🚨 Troubleshooting

### "No veo logs desde SSH"

**Causa:** Render captura logs de stdout/stderr y los muestra en el Dashboard, no en archivos.

**Solución:** Usa el Dashboard de Render para ver logs.

### "Quiero ver logs en tiempo real desde terminal"

**Solución:** Usa el Dashboard o configura tu aplicación para guardar logs en archivos (no recomendado en Render).

### "El servidor no responde"

**Verificar desde SSH:**
```bash
# Ver si el proceso está corriendo
ps aux | grep python

# Ver si el puerto está escuchando
netstat -tulpn | grep LISTEN

# Ver logs recientes del sistema
dmesg | tail -20
```

---

## ✅ Resumen

| Método | Cuándo Usar | Ventajas |
|--------|-------------|----------|
| **Dashboard** | Siempre | ⭐ Logs en tiempo real, filtros, búsqueda |
| **SSH + archivos log** | Si guardas logs en archivos | Ver logs históricos |
| **SSH + comandos** | Verificar estado | Debugging específico |
| **SSH + Django shell** | Probar código | Testing interactivo |

---

## 💡 Recomendación

**Para desarrollo y debugging:**

1. **Ver logs principales** → Dashboard de Render
2. **Verificar configuración** → SSH + comandos Django
3. **Probar conexiones** → SSH + scripts Python
4. **Debugging interactivo** → SSH + Django shell

**NO ejecutes el servidor manualmente desde SSH** - Render ya lo está haciendo por ti.

---

¿Necesitas ayuda para ver logs específicos? ¡Dime qué quieres verificar!
