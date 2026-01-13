# 🖼️ Problema: Imágenes de Vehículos No Se Muestran en Render

## ❌ Problema Identificado

Los logs de Render muestran errores como:
```
WARNING Not Found: /media/vehiculos/vehicle_1768274172390.jpg
```

### Causa Raíz

**Render tiene un sistema de archivos efímero**. Esto significa que:

1. ✅ Las imágenes se suben correctamente y se guardan en la base de datos
2. ✅ El campo `foto` en el modelo `Vehiculo` almacena la ruta (ej: `vehiculos/vehicle_xxx.jpg`)
3. ❌ **PERO** el archivo físico se pierde cuando:
   - Se hace un nuevo deploy
   - El servicio se reinicia
   - El contenedor se recicla

### ¿Por qué pasa esto?

En Render, cada vez que se hace un deploy:
- Se crea un nuevo contenedor
- El sistema de archivos se reinicia desde cero
- Los archivos que estaban en `MEDIA_ROOT` se pierden
- Solo persisten los datos en la base de datos

## 🔍 Diagnóstico

### Logs Agregados

Se agregaron logs detallados para diagnosticar el problema:

1. **En `serve_media` (urls.py)**:
   - Muestra la ruta que se intenta servir
   - Verifica si el archivo existe
   - Lista archivos en el directorio (si existe)

2. **En `VehiculoSerializer`**:
   - Muestra la URL relativa (`/media/vehiculos/...`)
   - Muestra la URL absoluta generada
   - Muestra el nombre del archivo en la BD

### Verificar en Logs de Render

Después de subir una imagen, busca en los logs:
```
📸 [VehiculoSerializer] Vehículo X - Foto URL absoluta: https://...
🔍 [serve_media] Intentando servir: vehiculos/vehicle_xxx.jpg
⚠️ [serve_media] Archivo no encontrado: /path/to/media/vehiculos/vehicle_xxx.jpg
```

## ✅ Soluciones

### Solución 1: Usar AWS S3 (Recomendado para Producción)

**Ventajas:**
- ✅ Persistencia garantizada
- ✅ Escalable
- ✅ CDN incluido
- ✅ No se pierden archivos

**Pasos:**

1. Crear bucket en S3
2. Configurar credenciales en Render (variables de entorno)
3. Descomentar y configurar en `settings.py`:

```python
# En settings.py, descomentar líneas 230-239
if not DEBUG:
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
    AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID', default='')
    AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY', default='')
    AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME', default='mecanimovil-media')
    AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME', default='us-east-1')
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'
    MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/'
```

4. Instalar dependencia:
```bash
pip install django-storages boto3
```

5. Agregar a `requirements.txt`:
```
django-storages
boto3
```

### Solución 2: Usar Disco Persistente en Render

Render ofrece discos persistentes para servicios web:

1. En el dashboard de Render, ir a tu servicio
2. Settings → Persistent Disk
3. Crear un disco persistente
4. Montar en `/persistent` o similar
5. Cambiar `MEDIA_ROOT` en `settings_production.py`:

```python
# Montar disco persistente
MEDIA_ROOT = '/persistent/media'
```

**Limitaciones:**
- ⚠️ Solo disponible en planes pagos
- ⚠️ Tamaño limitado
- ⚠️ No es tan escalable como S3

### Solución 3: Usar Cloudinary (Alternativa a S3)

Cloudinary ofrece un servicio gratuito para imágenes:

1. Crear cuenta en Cloudinary
2. Instalar: `pip install cloudinary django-cloudinary-storage`
3. Configurar en `settings.py`

**Ventajas:**
- ✅ Plan gratuito generoso
- ✅ Optimización automática de imágenes
- ✅ Transformaciones on-the-fly

## 🚨 Solución Temporal (Solo para Testing)

**NO RECOMENDADO PARA PRODUCCIÓN**

Si necesitas probar rápidamente sin configurar S3:

1. Las imágenes se seguirán perdiendo en cada deploy
2. Los usuarios verán placeholders en lugar de imágenes
3. Funciona para desarrollo/testing, pero no para producción

## 📋 Checklist de Implementación

Para implementar S3 (recomendado):

- [ ] Crear bucket en AWS S3
- [ ] Crear usuario IAM con permisos de S3
- [ ] Obtener Access Key ID y Secret Access Key
- [ ] Agregar variables de entorno en Render:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_STORAGE_BUCKET_NAME`
  - `AWS_S3_REGION_NAME`
- [ ] Instalar `django-storages` y `boto3`
- [ ] Descomentar configuración S3 en `settings.py`
- [ ] Hacer deploy y verificar que las imágenes persisten
- [ ] Migrar imágenes existentes (si las hay) a S3

## 🔗 Referencias

- [Render Persistent Disk](https://render.com/docs/disks)
- [Django Storages S3](https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html)
- [AWS S3 Setup Guide](https://docs.aws.amazon.com/s3/latest/userguide/create-bucket-overview.html)

## 📝 Notas

- El código actual funciona correctamente para desarrollo local
- El problema solo ocurre en producción (Render)
- Los logs ayudarán a diagnosticar el problema en tiempo real
- Una vez configurado S3, las imágenes persistirán correctamente
