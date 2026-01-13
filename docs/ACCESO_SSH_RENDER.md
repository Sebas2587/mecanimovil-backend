# 🔐 Acceso SSH a Render desde Cursor

Esta guía explica cómo conectarte a tu servicio en Render usando SSH desde tu terminal en Cursor, para poder ejecutar comandos directamente en el servidor de producción.

---

## 📋 Requisitos

### ✅ Compatibilidad de Servicios

SSH está disponible en los siguientes tipos de servicios:

| Tipo de Servicio | Dashboard Shell | SSH |
|------------------|-----------------|-----|
| **Web Service (Pago)** | 🟢 Sí | 🟢 Sí |
| **Private Service** | 🟢 Sí | 🟢 Sí |
| **Background Worker** | 🟢 Sí | 🟢 Sí |
| **Cron Job** | 🟨 Limitado | ❌ No |
| **Web Service (Gratis)** | ❌ No | ❌ No |
| **Static Sites / Datastores** | ❌ No | ❌ No |

> ⚠️ **Importante**: Si tu servicio está en el plan gratuito, SSH no estará disponible. Necesitas actualizar a un plan de pago.

---

## 🚀 Configuración Paso a Paso

### Paso 1: Generar una Clave SSH (si no tienes una)

Si ya tienes una clave SSH que quieres usar, puedes saltar este paso.

1. **Abre tu terminal en Cursor** (o cualquier terminal)

2. **Genera una clave SSH Ed25519** (recomendado):
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519
   ```

   O si prefieres RSA:
   ```bash
   ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa
   ```

3. **Cuando te pregunte por una passphrase**, puedes:
   - Presionar Enter para no usar passphrase (menos seguro pero más rápido)
   - O ingresar una passphrase (más seguro, recomendado)

4. **Se generarán dos archivos**:
   - `~/.ssh/id_ed25519` (clave privada - **NUNCA la compartas**)
   - `~/.ssh/id_ed25519.pub` (clave pública - esta es la que compartirás)

### Paso 2: Agregar tu Clave Pública a Render

1. **Copia tu clave pública al portapapeles**:
   
   En macOS:
   ```bash
   pbcopy < ~/.ssh/id_ed25519.pub
   ```
   
   En Linux:
   ```bash
   cat ~/.ssh/id_ed25519.pub | xclip -selection clipboard
   # O simplemente:
   cat ~/.ssh/id_ed25519.pub
   # Y copia manualmente el contenido
   ```

2. **Abre tu cuenta en Render Dashboard**:
   - Ve a: https://dashboard.render.com/settings#ssh-public-keys
   - O: Dashboard → Settings → SSH Public Keys

3. **Agrega tu clave SSH**:
   - Haz clic en **"+ Add SSH Public Key"**
   - **Name**: Pon un nombre descriptivo (ej: "Mi MacBook Pro", "Cursor Terminal")
   - **Key**: Pega tu clave pública (la que copiaste en el paso anterior)
   - Haz clic en **"Add SSH Public Key"**

   Tu clave pública se verá algo así:
   ```
   ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... tu-email@ejemplo.com
   ```

### Paso 3: Obtener el Comando SSH de tu Servicio

1. **Ve a tu servicio en Render Dashboard**
   - Ejemplo: `mecanimovil-api`

2. **Haz clic en el menú "Connect"** (arriba a la derecha)

3. **Selecciona la pestaña "SSH"**

4. **Copia el comando SSH** que aparece, se verá algo así:
   ```bash
   ssh srv-abc123def@ssh.oregon.render.com
   ```

   > **Nota**: El formato es: `ssh [SERVICE_ID]@ssh.[REGION].render.com`
   > - `srv-abc123def` es el ID de tu servicio
   > - `oregon` es la región donde está tu servicio (puede ser `virginia`, `frankfurt`, `singapore`, etc.)

### Paso 4: Conectarte desde Cursor

1. **Abre la terminal en Cursor**:
   - Presiona `` Ctrl + ` `` (backtick) o
   - Ve a: Terminal → New Terminal

2. **Ejecuta el comando SSH que copiaste**:
   ```bash
   ssh srv-abc123def@ssh.oregon.render.com
   ```

3. **Primera vez - Verificación de Fingerprint**:
   
   La primera vez que te conectes, verás algo como:
   ```
   The authenticity of host 'render.com (IP_ADDRESS)' can't be established.
   ED25519 key fingerprint is SHA256:XXXXX...
   Are you sure you want to continue connecting (yes/no)?
   ```
   
   **Verifica el fingerprint** comparándolo con los fingerprints oficiales de Render:
   
   | Región | Fingerprint |
   |--------|-------------|
   | **Oregon** | `SHA256:NCpSwboPnqL/Nvyy2Qc8Kgzpc3P/f3w5wDphhc+UZO0` |
   | **Virginia** | `SHA256:NCpSwboPnqL/Nvyy2Qc8Kgzpc3P/f3w5wDphhc+UZO0` |
   | **Frankfurt** | `SHA256:dBRrCEA0tBkvaYLzzDw/mzaANw6nUJO961Zx806spZs` |
   | **Singapore** | `SHA256:CUlRyv4TZ0vmHwmhsJkII/pz2cO4IgvR+ykqnRsOQFs` |
   
   Si coincide, escribe `yes` y presiona Enter.

4. **¡Conectado!** 🎉
   
   Ahora deberías ver algo como:
   ```bash
   Welcome to Render!
   [srv-abc123def@instance-xyz ~]$
   ```

---

## 🛠️ Uso de SSH en Render

### Comandos Útiles una vez Conectado

#### Navegación y Exploración
```bash
# Ver dónde estás
pwd

# Listar archivos
ls -la

# Navegar al directorio de la aplicación
cd /opt/render/project/src

# Ver estructura del proyecto
ls -la

# Ver variables de entorno
env | grep CPANEL
env | grep DATABASE
```

#### Comandos Django
```bash
# Ir al directorio del proyecto
cd /opt/render/project/src

# Activar entorno virtual (si existe)
source venv/bin/activate

# Verificar configuración Django
python manage.py check --deploy

# Ver migraciones
python manage.py showmigrations

# Ejecutar migraciones (si es necesario)
python manage.py migrate

# Abrir Django shell
python manage.py shell

# Verificar conexión a base de datos
python manage.py dbshell
```

#### Verificar Archivos y Logs
```bash
# Ver logs de la aplicación
tail -f /opt/render/project/src/logs/*.log

# Ver archivos de configuración
cat /opt/render/project/src/mecanimovilapp/settings.py | grep CPANEL

# Verificar si existen archivos subidos
ls -la /opt/render/project/src/media/
```

#### Verificar Conexión FTP (para nuestro caso de cPanel)
```bash
# Probar conexión FTP manualmente
python3 -c "
import ftplib
ftp = ftplib.FTP('ftp.mecanimovil.cl')
ftp.login('mecanimovil-media@mecanimovil.cl', 'TU_PASSWORD')
print('Conexión FTP exitosa')
print('Directorio actual:', ftp.pwd())
ftp.quit()
"
```

#### Verificar Variables de Entorno
```bash
# Ver todas las variables de entorno relacionadas con cPanel
env | grep -i cpanel

# Ver todas las variables de entorno
env

# Verificar una variable específica
echo $CPANEL_FTP_ROOT
echo $CPANEL_MEDIA_URL
```

---

## 🔍 Conectarse a una Instancia Específica

Si tu servicio tiene múltiples instancias (escalado), puedes conectarte a una específica:

1. **Encuentra el slug de la instancia** en los logs:
   ```
   [instance-d4e5f] Starting server...
   ```

2. **Agrega el slug al comando SSH**:
   ```bash
   ssh srv-abc123def-d4e5f@ssh.oregon.render.com
   ```
   
   Formato: `ssh [SERVICE_ID]-[INSTANCE_SLUG]@ssh.[REGION].render.com`

---

## 🚨 Troubleshooting

### Error: "Permission denied (publickey)"

**Causas posibles:**
1. No agregaste tu clave pública a Render
2. Estás usando la clave SSH incorrecta
3. Tu servicio está en plan gratuito (SSH no disponible)

**Solución:**
```bash
# Verificar qué clave estás usando
ssh -v srv-abc123def@ssh.oregon.render.com

# Verificar claves cargadas en ssh-agent
ssh-add -l

# Si no ves tu clave, agrégala
ssh-add ~/.ssh/id_ed25519
```

### Error: "Host key verification failed"

**Solución:**
```bash
# Eliminar la entrada antigua de known_hosts
ssh-keygen -R ssh.oregon.render.com

# O editar manualmente
nano ~/.ssh/known_hosts
# Elimina la línea que contiene render.com
```

### No veo la pestaña SSH en el Dashboard

**Posibles causas:**
- Tu servicio está en plan gratuito (SSH no disponible)
- Tu servicio no es compatible con SSH (ej: Static Site)

**Solución:**
- Actualiza a un plan de pago
- O usa el Shell del Dashboard (más limitado)

### La conexión se cierra automáticamente

**Causas:**
- Render cierra conexiones SSH cuando:
  - El servicio se reinicia/redeploya
  - Hay mantenimiento programado (con 1 hora de aviso)

**Solución:**
- Para comandos largos, considera usar [One-off Jobs](https://render.com/docs/one-off-jobs) en lugar de SSH

---

## 💡 Alternativa: Render CLI

Puedes usar el Render CLI para conectarte más fácilmente:

### Instalación
```bash
# macOS
brew install render

# O con npm
npm install -g render-cli
```

### Configuración
```bash
# Iniciar sesión
render login

# Conectarse a un servicio
render ssh

# Esto abrirá un menú interactivo para seleccionar el servicio
```

---

## 📝 Ejemplo: Verificar Configuración de cPanel desde SSH

```bash
# 1. Conectarse a Render
ssh srv-abc123def@ssh.oregon.render.com

# 2. Ir al directorio del proyecto
cd /opt/render/project/src

# 3. Verificar variables de entorno
echo "CPANEL_FTP_HOST: $CPANEL_FTP_HOST"
echo "CPANEL_FTP_USER: $CPANEL_FTP_USER"
echo "CPANEL_FTP_ROOT: $CPANEL_FTP_ROOT"
echo "CPANEL_MEDIA_URL: $CPANEL_MEDIA_URL"

# 4. Probar conexión FTP
python3 << EOF
import ftplib
import os
ftp_host = os.getenv('CPANEL_FTP_HOST')
ftp_user = os.getenv('CPANEL_FTP_USER')
ftp_pass = os.getenv('CPANEL_FTP_PASSWORD')

try:
    ftp = ftplib.FTP(ftp_host)
    ftp.login(ftp_user, ftp_pass)
    print(f"✅ Conexión FTP exitosa")
    print(f"Directorio actual: {ftp.pwd()}")
    ftp.quit()
except Exception as e:
    print(f"❌ Error: {e}")
EOF

# 5. Verificar configuración Django
python3 manage.py shell << EOF
from django.conf import settings
print(f"STORAGE_TYPE: {getattr(settings, 'STORAGE_TYPE', 'No definido')}")
print(f"DEFAULT_FILE_STORAGE: {getattr(settings, 'DEFAULT_FILE_STORAGE', 'No definido')}")
print(f"CPANEL_MEDIA_URL: {getattr(settings, 'CPANEL_MEDIA_URL', 'No definido')}")
EOF
```

---

## ✅ Mejores Prácticas

1. **Usa SSH solo cuando sea necesario**: Para debugging específico o verificación
2. **No modifiques archivos directamente**: Los cambios se perderán en el próximo deploy
3. **Usa logs para debugging**: Los logs son más útiles para la mayoría de casos
4. **Cierra la conexión cuando termines**: `exit` o `Ctrl+D`
5. **No ejecutes comandos destructivos**: Como `rm -rf` o `drop database`

---

## 🔗 Referencias

- [Documentación oficial de Render sobre SSH](https://render.com/docs/ssh)
- [Render CLI Documentation](https://render.com/docs/cli)
- [Render Public Key Fingerprints](https://render.com/docs/ssh#renders-public-key-fingerprints)

---

## 📋 Checklist de Configuración

- [ ] Servicio en plan de pago (requisito para SSH)
- [ ] Clave SSH generada (`~/.ssh/id_ed25519`)
- [ ] Clave pública agregada a Render Dashboard
- [ ] Comando SSH copiado del Dashboard
- [ ] Primera conexión exitosa
- [ ] Fingerprint verificado
- [ ] Puedo ejecutar comandos en el servidor

---

¡Listo! Ahora puedes conectarte a Render desde Cursor y ejecutar comandos directamente en producción. 🎉
