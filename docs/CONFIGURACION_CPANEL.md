# 📁 Configuración de Almacenamiento en cPanel

Esta guía explica cómo configurar cPanel para almacenar y servir las imágenes de vehículos desde tu servidor cPanel, evitando el problema del sistema de archivos efímero en Render.

## 📋 Tabla de Contenidos

1. [Ventajas de usar cPanel](#ventajas-de-usar-cpanel)
2. [Configuración en cPanel](#configuración-en-cpanel)
3. [Configuración en Render](#configuración-en-render)
4. [Verificación](#verificación)
5. [Migración a S3 (futuro)](#migración-a-s3-futuro)

---

## ✅ Ventajas de usar cPanel

- ✅ **Usa infraestructura existente**: Aprovecha tu servidor cPanel actual
- ✅ **Sin costos adicionales**: No necesitas servicios externos
- ✅ **Control total**: Tienes control completo sobre los archivos
- ✅ **Fácil migración**: Cambiar a S3 es solo cambiar una variable de entorno

---

## 🔧 Configuración en cPanel

### Paso 1: Crear cuenta FTP dedicada

1. **Accede a cPanel** de tu hosting
2. Ve a **"Cuentas FTP"** o **"FTP Accounts"**
3. Haz clic en **"Agregar cuenta FTP"** o **"Add FTP Account"**

### Paso 2: Configurar la cuenta FTP

Configura la cuenta con estos valores:

- **Usuario FTP**: `mecanimovil-media` (o el nombre que prefieras)
  - Este será el usuario que Render usará para subir archivos
  
- **Dominio**: Selecciona tu dominio principal
  - Ejemplo: `tudominio.com`

- **Directorio**: `/public_html/media` o `/home/usuario/public_html/media`
  - ⚠️ **IMPORTANTE**: Este directorio debe ser accesible vía HTTP
  - Este es el directorio donde se guardarán todas las imágenes
  - El sistema creará subdirectorios automáticamente (ej: `vehiculos/`)

- **Cuota de disco**: Configura según tus necesidades
  - Recomendado: Al menos 1GB para empezar

- **Contraseña**: Genera una contraseña segura
  - ⚠️ **IMPORTANTE**: Guarda esta contraseña, la necesitarás para Render

### Paso 3: Obtener información de conexión FTP

Después de crear la cuenta, cPanel te mostrará la información de conexión:

- **Servidor FTP**: Generalmente es `ftp.tudominio.com` o la IP del servidor
- **Puerto**: `21` (puerto estándar FTP)
- **Usuario completo**: `mecanimovil-media@tudominio.com` (o similar)
- **Directorio remoto**: `/public_html/media` (o el que configuraste)

### Paso 4: Configurar permisos del directorio

1. Ve a **"Administrador de archivos"** o **"File Manager"** en cPanel
2. Navega a `/public_html/media`
3. Si el directorio no existe, créalo:
   - Haz clic derecho → **"Crear carpeta"** → Nombre: `media`
4. Configura permisos:
   - Haz clic derecho en `media` → **"Cambiar permisos"** o **"Change Permissions"**
   - Configura: **`755`** (lectura, escritura y ejecución para el propietario)
   - Esto permite que la cuenta FTP pueda escribir archivos

### Paso 5: Verificar acceso HTTP

Asegúrate de que el directorio sea accesible vía HTTP:

1. Crea un archivo de prueba: `test.txt` en `/public_html/media/`
2. Accede desde el navegador: `https://tudominio.com/media/test.txt`
3. Si puedes ver el archivo, la configuración HTTP está correcta
4. Elimina el archivo de prueba después

---

## ⚙️ Configuración en Render

### Paso 1: Agregar variables de entorno

En el dashboard de Render, ve a tu servicio y agrega estas variables de entorno:

```bash
# Tipo de almacenamiento (cpanel, s3, o local)
STORAGE_TYPE=cpanel

# Configuración FTP de cPanel
CPANEL_FTP_HOST=ftp.tudominio.com
CPANEL_FTP_USER=mecanimovil-media@tudominio.com
CPANEL_FTP_PASSWORD=tu_contraseña_segura_aqui
CPANEL_FTP_ROOT=/public_html/media

# URL pública donde se servirán los archivos
CPANEL_MEDIA_URL=https://tudominio.com/media/
```

### Paso 2: Explicación de cada variable

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `STORAGE_TYPE` | Tipo de almacenamiento a usar | `cpanel` |
| `CPANEL_FTP_HOST` | Servidor FTP de cPanel | `ftp.tudominio.com` |
| `CPANEL_FTP_USER` | Usuario FTP completo | `mecanimovil-media@tudominio.com` |
| `CPANEL_FTP_PASSWORD` | Contraseña de la cuenta FTP | `MiPassword123!` |
| `CPANEL_FTP_ROOT` | Ruta en el servidor donde guardar archivos | `/public_html/media` |
| `CPANEL_MEDIA_URL` | URL pública para acceder a los archivos | `https://tudominio.com/media/` |

### Paso 3: Verificar configuración

Después de agregar las variables, Render hará un nuevo deploy automáticamente.

---

## ✅ Verificación

### 1. Verificar en logs de Render

Después de subir una imagen, busca en los logs:

```
✅ [CPanelStorage] Archivo subido: /public_html/media/vehiculos/vehicle_xxx.jpg
```

Si ves este mensaje, la subida fue exitosa.

### 2. Verificar en cPanel

1. Accede a **"Administrador de archivos"** en cPanel
2. Navega a `/public_html/media/vehiculos/`
3. Deberías ver los archivos de imágenes subidos

### 3. Verificar acceso HTTP

1. Abre un navegador
2. Accede a: `https://tudominio.com/media/vehiculos/vehicle_xxx.jpg`
3. Si la imagen se muestra, la configuración está correcta

### 4. Verificar en la app móvil

1. Sube una imagen de vehículo desde la app
2. Verifica que la imagen se muestre correctamente
3. Revisa los logs de la app para ver la URL de la imagen

---

## 🔄 Migración a S3 (futuro)

Cuando quieras migrar a AWS S3, solo necesitas cambiar las variables de entorno en Render:

### Paso 1: Configurar S3

1. Crea un bucket en AWS S3
2. Configura las credenciales IAM
3. Obtén Access Key ID y Secret Access Key

### Paso 2: Cambiar variables en Render

Cambia estas variables de entorno:

```bash
# Cambiar tipo de almacenamiento
STORAGE_TYPE=s3

# Configuración de S3
AWS_ACCESS_KEY_ID=tu_access_key_id
AWS_SECRET_ACCESS_KEY=tu_secret_access_key
AWS_STORAGE_BUCKET_NAME=mecanimovil-media
AWS_S3_REGION_NAME=us-east-1
```

### Paso 3: Migrar archivos existentes (opcional)

Si quieres migrar los archivos existentes de cPanel a S3:

1. Descarga todos los archivos de `/public_html/media/` desde cPanel
2. Sube los archivos al bucket de S3 manteniendo la misma estructura
3. Los nuevos archivos se subirán automáticamente a S3

### Paso 4: Verificar

1. Sube una nueva imagen desde la app
2. Verifica que se suba a S3
3. Verifica que la URL apunte a S3

---

## 🐛 Solución de Problemas

### Error: "Configuración FTP incompleta"

**Causa**: Faltan variables de entorno en Render

**Solución**: Verifica que todas las variables `CPANEL_FTP_*` estén configuradas

### Error: "Error conectando a FTP"

**Causa**: Credenciales incorrectas o servidor FTP no accesible

**Solución**:
1. Verifica que el servidor FTP sea accesible desde Render
2. Verifica usuario y contraseña
3. Verifica que el puerto 21 esté abierto

### Error: "No se pudo crear directorio"

**Causa**: Permisos insuficientes en el servidor

**Solución**:
1. Verifica permisos del directorio en cPanel (debe ser 755)
2. Verifica que la cuenta FTP tenga permisos de escritura

### Las imágenes no se muestran en la app

**Causa**: URL incorrecta o archivo no accesible vía HTTP

**Solución**:
1. Verifica que `CPANEL_MEDIA_URL` sea correcta
2. Verifica que el archivo exista en cPanel
3. Verifica que el archivo sea accesible vía HTTP (abre la URL en el navegador)

---

## 📝 Notas Importantes

1. **Seguridad**: 
   - Nunca compartas las credenciales FTP
   - Usa contraseñas seguras
   - Considera usar SFTP si tu hosting lo soporta (requiere configuración adicional)

2. **Rendimiento**:
   - cPanel es adecuado para empezar
   - Para mayor escalabilidad, considera migrar a S3 más adelante

3. **Backup**:
   - Asegúrate de tener backups del directorio `/public_html/media/`
   - cPanel generalmente incluye backups automáticos

4. **Límites**:
   - Verifica los límites de almacenamiento de tu plan de hosting
   - Monitorea el uso de espacio en cPanel

---

## 🔗 Referencias

- [Documentación de Django Storage](https://docs.djangoproject.com/en/stable/topics/files/#file-storage)
- [Guía de cuentas FTP en cPanel](https://docs.cpanel.net/cpanel/files/ftp-accounts/)
- [Documentación de migración a S3](./PROBLEMA_IMAGENES_RENDER.md)

---

## ✅ Checklist de Configuración

- [ ] Cuenta FTP creada en cPanel
- [ ] Directorio `/public_html/media` creado con permisos 755
- [ ] Acceso HTTP verificado (puedes acceder a archivos vía URL)
- [ ] Variables de entorno configuradas en Render:
  - [ ] `STORAGE_TYPE=cpanel`
  - [ ] `CPANEL_FTP_HOST`
  - [ ] `CPANEL_FTP_USER`
  - [ ] `CPANEL_FTP_PASSWORD`
  - [ ] `CPANEL_FTP_ROOT`
  - [ ] `CPANEL_MEDIA_URL`
- [ ] Deploy realizado en Render
- [ ] Prueba de subida de imagen exitosa
- [ ] Imagen accesible vía HTTP
- [ ] Imagen visible en la app móvil

---

¡Listo! Tu configuración de cPanel está completa. Las imágenes ahora se almacenarán en tu servidor cPanel y se servirán directamente desde allí.
