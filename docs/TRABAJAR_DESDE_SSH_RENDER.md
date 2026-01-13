# 🛠️ Trabajar desde SSH en Render

Esta guía explica qué puedes y **NO puedes** hacer cuando te conectas a Render vía SSH.

---

## ⚠️ Limitaciones Importantes

### ❌ NO puedes hacer:

1. **Modificar archivos directamente** - Los cambios se perderán en el próximo deploy
2. **Ejecutar el servidor manualmente** - Ya está corriendo como servicio
3. **Instalar paquetes del sistema** - Render no permite modificaciones permanentes
4. **Cambiar configuración del sistema** - El sistema es de solo lectura

### ✅ SÍ puedes hacer:

1. **Ver logs en tiempo real**
2. **Verificar variables de entorno**
3. **Ejecutar comandos Django** (migraciones, shell, etc.)
4. **Probar conexiones** (FTP, base de datos, etc.)
5. **Verificar configuración y archivos**
6. **Debugging específico**

---

## 🔄 Flujo de Trabajo Correcto

### 1. Desarrollo Local (en Cursor)

```bash
# Trabajas en tu máquina local
cd mecanimovil-backend
# Editas archivos
# Pruebas localmente
python manage.py runserver
```

### 2. Commit y Push

```bash
git add .
git commit -m "fix: Corregir problema de imágenes"
git push origin main
```

### 3. Render Hace Deploy Automático

- Render detecta el push
- Construye y despliega automáticamente
- Puedes ver el progreso en "Events"

### 4. Verificar desde SSH (Opcional)

```bash
# Conectarte a Render
ssh srv-abc123@ssh.oregon.render.com

# Verificar que los cambios se aplicaron
cd /opt/render/project/src
cat mecanimovilapp/storage/cpanel_storage.py | grep "tu_cambio"
```

---

## 📋 Comandos Útiles desde SSH

### Verificar Variables de Entorno

```bash
# Ver todas las variables de cPanel
env | grep CPANEL

# Ver una variable específica
echo $CPANEL_FTP_HOST
echo $CPANEL_MEDIA_URL
```

### Verificar Configuración Django

```bash
cd /opt/render/project/src

# Verificar configuración
python3 manage.py shell << 'EOF'
from django.conf import settings
print("STORAGE_TYPE:", getattr(settings, 'STORAGE_TYPE', 'No definido'))
print("CPANEL_FTP_ROOT:", getattr(settings, 'CPANEL_FTP_ROOT', 'No definido'))
EOF
```

### Probar Conexión FTP

```bash
python3 << 'EOF'
import ftplib
import os

ftp = ftplib.FTP(os.getenv('CPANEL_FTP_HOST'))
ftp.login(os.getenv('CPANEL_FTP_USER'), os.getenv('CPANEL_FTP_PASSWORD'))
print("✅ Conexión FTP exitosa")
print("Directorio actual:", ftp.pwd())
ftp.quit()
EOF
```

### Ver Logs en Tiempo Real

```bash
# Los logs se ven mejor desde el Dashboard
# Pero puedes ver archivos de log si existen
tail -f /opt/render/project/src/logs/*.log
```

### Ejecutar Comandos Django

```bash
cd /opt/render/project/src

# Migraciones
python3 manage.py migrate

# Django shell
python3 manage.py shell

# Verificar migraciones
python3 manage.py showmigrations

# Verificar configuración
python3 manage.py check --deploy
```

### Verificar Archivos Subidos

```bash
# Ver vehículos en base de datos
python3 manage.py shell << 'EOF'
from apps.vehiculos.models import Vehiculo
for v in Vehiculo.objects.all()[:5]:
    print(f"Vehículo {v.id}: {v.foto.name if v.foto else 'Sin foto'}")
EOF
```

---

## 🔍 Script de Diagnóstico

He creado un script que puedes ejecutar desde SSH para diagnosticar problemas:

**Ubicación:** `scripts/diagnostico_render.sh`

**Cómo usarlo:**

1. **Copia el contenido del script** a tu sesión SSH en Render
2. **O ejecuta los comandos manualmente** uno por uno

El script verifica:
- ✅ Variables de entorno
- ✅ Configuración Django
- ✅ Conexión FTP
- ✅ Archivos en el servidor FTP
- ✅ Vehículos en la base de datos

---

## 💡 Ejemplo: Diagnosticar Problema de Imágenes

### Paso 1: Conectarte a Render

```bash
ssh srv-abc123@ssh.oregon.render.com
```

### Paso 2: Ejecutar Diagnóstico

```bash
cd /opt/render/project/src

# Verificar variables de entorno
env | grep CPANEL

# Probar conexión FTP
python3 << 'EOF'
import ftplib
import os
ftp = ftplib.FTP(os.getenv('CPANEL_FTP_HOST'))
ftp.login(os.getenv('CPANEL_FTP_USER'), os.getenv('CPANEL_FTP_PASSWORD'))
print("Directorio actual:", ftp.pwd())
ftp.cwd('public_html/images')
print("Navegado a images/")
try:
    ftp.cwd('mecanimovil-app-media')
    print("✅ Directorio mecanimovil-app-media existe")
    files = ftp.nlst()
    print(f"Archivos encontrados: {len(files)}")
    for f in files[:10]:
        if f not in ['.', '..']:
            print(f"  - {f}")
except:
    print("❌ Directorio mecanimovil-app-media NO existe")
ftp.quit()
EOF
```

### Paso 3: Si Encuentras Problemas

1. **Si faltan variables de entorno**: Agrégalas en Render Dashboard → Environment
2. **Si el directorio no existe**: Créalo manualmente en cPanel
3. **Si hay errores de conexión**: Verifica credenciales FTP

### Paso 4: Hacer Correcciones

**NO edites archivos desde SSH**. En su lugar:

1. **Edita localmente en Cursor**
2. **Haz commit y push**
3. **Render hace deploy automático**
4. **Verifica desde SSH que los cambios se aplicaron**

---

## 🚨 Errores Comunes

### "Permission denied" al editar archivos

**Causa**: Render no permite modificar archivos directamente.

**Solución**: Edita localmente y haz deploy.

### "Command not found: python"

**Causa**: Python puede estar como `python3`.

**Solución**: Usa `python3` en lugar de `python`.

### "No such file or directory: /opt/render/project/src"

**Causa**: El directorio puede estar en otra ubicación.

**Solución**: Busca el proyecto:
```bash
find /opt -name "manage.py" -type f
```

---

## ✅ Resumen

| Acción | Dónde Hacerlo | Método |
|--------|---------------|--------|
| **Editar código** | Local (Cursor) | Editar archivos → Commit → Push |
| **Ver logs** | Render Dashboard | Logs en tiempo real |
| **Verificar config** | SSH en Render | Comandos de diagnóstico |
| **Probar conexiones** | SSH en Render | Scripts Python |
| **Ejecutar migraciones** | SSH en Render | `python3 manage.py migrate` |
| **Debugging** | SSH en Render | Django shell, comandos |

---

## 🎯 Para tu Caso Específico (Problema de Imágenes)

1. **Conéctate a Render vía SSH**
2. **Ejecuta el script de diagnóstico** (`scripts/diagnostico_render.sh`)
3. **Identifica el problema** (variables faltantes, directorio no existe, etc.)
4. **Si necesitas hacer cambios**:
   - Edita localmente en Cursor
   - Commit y push
   - Render hace deploy
5. **Verifica desde SSH** que los cambios se aplicaron

---

¿Necesitas ayuda con algún comando específico desde SSH? ¡Dime qué quieres verificar!
