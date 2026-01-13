# 🔍 Verificar Configuración de cPanel en Render

Este documento te ayuda a verificar si la configuración de cPanel está correcta en Render.

## ⚠️ Problema Actual

Los logs muestran:
```
GET /media/vehiculos/vehicle_xxx.jpg" 404
WARNING Not Found: /media/vehiculos/vehicle_xxx.jpg
```

Esto indica que:
1. Las imágenes se están guardando localmente en Render (se pierden)
2. Las URLs se están construyendo como relativas (`/media/...`) en lugar de URLs de cPanel

## ✅ Verificación Paso a Paso

### Paso 1: Verificar Variables de Entorno en Render

Ve al dashboard de Render → Tu servicio → Environment

**Variables REQUERIDAS:**

```bash
STORAGE_TYPE=cpanel
CPANEL_FTP_HOST=ftp.mecanimovil.cl
CPANEL_FTP_USER=mecanimovil-media@mecanimovil.cl
CPANEL_FTP_PASSWORD=tu_contraseña
CPANEL_FTP_ROOT=public_html/images/mecanimovil-app-media
CPANEL_MEDIA_URL=https://mecanimovil.cl/images/mecanimovil-app-media/
```

**Verifica que TODAS estén configuradas correctamente.**

### Paso 2: Verificar Logs Después del Deploy

Después de que Render haga deploy, busca en los logs:

**Al iniciar el servicio, deberías ver:**
```
🔍 [CPanelStorage.__init__] location: public_html/images/mecanimovil-app-media
🔍 [CPanelStorage.__init__] base_url: https://mecanimovil.cl/images/mecanimovil-app-media/
🔍 [CPanelStorage.__init__] ftp_host: ftp.mecanimovil.cl
```

**Si NO ves estos logs:**
- El storage backend no se está inicializando
- `STORAGE_TYPE` no está configurado o las variables CPANEL_* no están disponibles

### Paso 3: Verificar Logs al Subir una Imagen

Cuando un usuario sube una imagen, busca en los logs:

**Deberías ver:**
```
✅ [CPanelStorage] Archivo subido: public_html/images/mecanimovil-app-media/vehiculos/vehicle_xxx.jpg
🔍 [VehiculoSerializer] Vehículo X - STORAGE_TYPE: cpanel
🔍 [VehiculoSerializer] Vehículo X - DEFAULT_FILE_STORAGE: mecanimovilapp.storage.cpanel_storage.CPanelStorage
📸 [VehiculoSerializer] Vehículo X - URL desde storage: /media/vehiculos/vehicle_xxx.jpg
📸 [VehiculoSerializer] Vehículo X - URL construida de cPanel: https://mecanimovil.cl/images/mecanimovil-app-media/vehiculos/vehicle_xxx.jpg
```

**Si ves esto:**
```
⚠️ [VehiculoSerializer] Vehículo X - STORAGE_TYPE=cpanel pero CPANEL_MEDIA_URL no está configurado
```
- `CPANEL_MEDIA_URL` no está configurado en Render

**Si ves esto:**
```
🔍 [VehiculoSerializer] Vehículo X - STORAGE_TYPE: local
```
- `STORAGE_TYPE` no está configurado o está en 'local'

### Paso 4: Verificar que el Archivo se Subió a cPanel

1. Accede a cPanel → "Administrador de archivos"
2. Navega a: `public_html/images/mecanimovil-app-media/vehiculos/`
3. Deberías ver los archivos de imágenes

**Si NO ves archivos:**
- El storage backend no está funcionando
- Verifica credenciales FTP
- Verifica permisos del directorio

### Paso 5: Verificar que la URL Funciona

1. Abre un navegador
2. Accede a: `https://mecanimovil.cl/images/mecanimovil-app-media/vehiculos/vehicle_xxx.jpg`
3. Deberías ver la imagen

**Si NO funciona:**
- Verifica que `CPANEL_MEDIA_URL` sea correcta
- Verifica que el archivo exista en cPanel
- Verifica permisos del archivo (644)

## 🐛 Problemas Comunes y Soluciones

### Problema 1: "STORAGE_TYPE: local" en los logs

**Causa:** `STORAGE_TYPE` no está configurado en Render

**Solución:**
1. Ve a Render → Environment
2. Agrega: `STORAGE_TYPE=cpanel`
3. Haz un nuevo deploy

### Problema 2: "CPANEL_MEDIA_URL no está configurado"

**Causa:** `CPANEL_MEDIA_URL` no está configurado o está vacío

**Solución:**
1. Ve a Render → Environment
2. Agrega: `CPANEL_MEDIA_URL=https://mecanimovil.cl/images/mecanimovil-app-media/`
3. Verifica que la URL termine con `/`
4. Haz un nuevo deploy

### Problema 3: "Error conectando a FTP"

**Causa:** Credenciales FTP incorrectas o servidor no accesible

**Solución:**
1. Verifica `CPANEL_FTP_HOST`, `CPANEL_FTP_USER`, `CPANEL_FTP_PASSWORD`
2. Prueba conectarte con un cliente FTP para verificar credenciales
3. Verifica que el puerto 21 esté abierto

### Problema 4: Archivos no se suben a cPanel

**Causa:** El storage backend no se está usando

**Solución:**
1. Verifica que `DEFAULT_FILE_STORAGE` esté configurado
2. Verifica los logs al iniciar el servicio
3. Verifica que todas las variables CPANEL_* estén configuradas

### Problema 5: URLs siguen siendo relativas (`/media/...`)

**Causa:** El serializer no está construyendo URLs de cPanel

**Solución:**
1. Verifica que `CPANEL_MEDIA_URL` esté configurado
2. Verifica los logs del serializer
3. Si ves "URL construida de cPanel", el problema está resuelto
4. Si no, verifica que `STORAGE_TYPE=cpanel` esté configurado

## 📋 Checklist de Verificación

- [ ] Todas las variables de entorno están configuradas en Render
- [ ] `STORAGE_TYPE=cpanel` está configurado
- [ ] `CPANEL_MEDIA_URL` está configurado y es correcta
- [ ] Los logs muestran que CPanelStorage se inicializa correctamente
- [ ] Los logs muestran que los archivos se suben a cPanel
- [ ] Los logs muestran que las URLs se construyen correctamente
- [ ] Los archivos existen en cPanel
- [ ] Las URLs funcionan en el navegador
- [ ] Las imágenes se muestran en la app móvil

## 🔍 Comandos para Verificar en Render

Si tienes acceso SSH a Render, puedes verificar:

```bash
# Verificar variables de entorno
env | grep CPANEL
env | grep STORAGE

# Verificar que el storage se está usando
python manage.py shell
>>> from django.conf import settings
>>> print(settings.STORAGE_TYPE)
>>> print(settings.DEFAULT_FILE_STORAGE)
>>> print(settings.CPANEL_MEDIA_URL)
```

## 📝 Notas Importantes

1. **Después de configurar variables de entorno, Render hace deploy automáticamente**
2. **Los logs aparecen después de que un usuario suba una imagen**
3. **Si no ves los logs del serializer, el serializer no se está ejecutando**
4. **Las imágenes antiguas pueden tener URLs relativas guardadas en la BD, pero el serializer las convertirá automáticamente**

---

**Si después de verificar todo esto el problema persiste, comparte los logs completos de Render para diagnosticar mejor el problema.**
