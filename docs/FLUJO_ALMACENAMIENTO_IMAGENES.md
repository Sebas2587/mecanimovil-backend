# 📸 Flujo de Almacenamiento de Imágenes en cPanel

Este documento explica cómo funciona el proceso completo cuando un usuario sube una foto de vehículo.

## 🔄 Flujo Completo

### 1. Usuario sube foto desde la app móvil

```
App Móvil → POST /api/vehiculos/{id}/ (con foto en FormData)
```

### 2. Django recibe la petición

- El `VehiculoViewSet` recibe la petición con el archivo
- Django procesa el archivo usando el `ImageField` del modelo `Vehiculo`

### 3. Storage backend guarda el archivo

Cuando `STORAGE_TYPE=cpanel` en producción:

1. **Django llama al método `_save()` del `CPanelStorage`**
   - El archivo se guarda temporalmente en disco local
   - Se establece conexión FTP con cPanel
   - Se crean los directorios necesarios si no existen
   - El archivo se sube vía FTP a: `public_html/images/mecanimovil-app-media/vehiculos/vehicle_xxx.jpg`
   - El archivo temporal se elimina

2. **Django guarda la referencia en la BD**
   - El campo `foto` en la tabla `vehiculos` almacena: `vehiculos/vehicle_xxx.jpg`
   - Esta es la ruta relativa, no la URL completa

### 4. Serializer construye la URL para la respuesta

Cuando el serializer necesita devolver la URL de la imagen:

1. **El serializer llama a `get_foto()`**
2. **Verifica el tipo de storage:**
   - Si `STORAGE_TYPE=cpanel` o `s3`: Usa `obj.foto.url` directamente
   - Si `STORAGE_TYPE=local`: Construye URL con `request.build_absolute_uri()`

3. **El método `url()` del `CPanelStorage` se ejecuta:**
   - Recibe: `vehiculos/vehicle_xxx.jpg` (nombre relativo)
   - Construye: `https://mecanimovil.cl/images/mecanimovil-app-media/vehiculos/vehicle_xxx.jpg`
   - Retorna la URL completa

### 5. App móvil recibe la URL

- La app recibe la URL completa de cPanel
- React Native descarga la imagen desde cPanel
- React Native cachea la imagen automáticamente

## 📁 Estructura de Directorios en cPanel

```
public_html/
└── images/
    └── mecanimovil-app-media/
        ├── vehiculos/
        │   ├── vehicle_1768274172390.jpg
        │   ├── vehicle_1768274172391.jpg
        │   └── ...
        ├── servicios_photos/
        │   └── ...
        └── checklist_photos/
            └── ...
```

## 🔍 Referencias en la Base de Datos

El campo `foto` en la tabla `vehiculos` almacena solo la ruta relativa:

```sql
-- Ejemplo de registro en la BD
id | patente | foto
1  | ABC123  | vehiculos/vehicle_1768274172390.jpg
```

**NO almacena la URL completa**, eso se construye dinámicamente.

## ✅ Verificación del Flujo

### 1. Verificar que el archivo se subió a cPanel

1. Accede a cPanel → "Administrador de archivos"
2. Navega a: `public_html/images/mecanimovil-app-media/vehiculos/`
3. Deberías ver los archivos de imágenes

### 2. Verificar que la URL es correcta

1. Revisa los logs de Render después de subir una imagen:
   ```
   ✅ [CPanelStorage] Archivo subido: public_html/images/mecanimovil-app-media/vehiculos/vehicle_xxx.jpg
   📸 [VehiculoSerializer] Vehículo X - Foto URL desde storage (cpanel): https://mecanimovil.cl/images/mecanimovil-app-media/vehiculos/vehicle_xxx.jpg
   ```

2. Abre la URL en el navegador:
   ```
   https://mecanimovil.cl/images/mecanimovil-app-media/vehiculos/vehicle_xxx.jpg
   ```
   Deberías ver la imagen

### 3. Verificar en la app móvil

1. Sube una foto desde la app
2. Verifica que la imagen se muestre correctamente
3. Revisa los logs de la app para ver la URL recibida

## 🎯 Información del Usuario y Vehículo

Actualmente, el nombre del archivo se genera automáticamente por Django:

- **Formato**: `vehicle_{timestamp}.jpg`
- **Ubicación**: `vehiculos/vehicle_{timestamp}.jpg`
- **Referencia en BD**: El campo `foto` almacena la ruta relativa
- **Relación**: El vehículo está vinculado al usuario a través del campo `cliente`

### ¿Dónde está la referencia del usuario y vehículo?

1. **Usuario**: Está en la relación `vehiculo.cliente.usuario`
2. **Vehículo**: El archivo está asociado directamente al vehículo a través del campo `foto`
3. **Nombre del archivo**: Django genera un nombre único automáticamente

### Si quieres incluir más información en el nombre del archivo

Puedes modificar el modelo para usar una función personalizada en `upload_to`:

```python
def upload_to_vehiculo(instance, filename):
    """
    Genera un nombre de archivo con información del vehículo y usuario
    """
    ext = filename.split('.')[-1]
    timestamp = int(time.time() * 1000)
    usuario_id = instance.cliente.usuario.id if instance.cliente and instance.cliente.usuario else 'unknown'
    vehiculo_id = instance.id if instance.id else 'new'
    return f'vehiculos/user_{usuario_id}_veh_{vehiculo_id}_{timestamp}.{ext}'

class Vehiculo(models.Model):
    foto = models.ImageField(
        upload_to=upload_to_vehiculo,  # Función personalizada
        blank=True, 
        null=True
    )
```

## ⚙️ Configuración Requerida

### Variables de entorno en Render:

```bash
STORAGE_TYPE=cpanel
CPANEL_FTP_HOST=ftp.mecanimovil.cl
CPANEL_FTP_USER=mecanimovil-media@mecanimovil.cl
CPANEL_FTP_PASSWORD=tu_contraseña
CPANEL_FTP_ROOT=public_html/images/mecanimovil-app-media
CPANEL_MEDIA_URL=https://mecanimovil.cl/images/mecanimovil-app-media/
```

## 🚨 Puntos Importantes

1. **Render NO sirve las imágenes**: Las imágenes se sirven directamente desde cPanel vía HTTP
2. **Render solo sube**: Render solo actúa como intermediario para subir archivos a cPanel
3. **La app descarga desde cPanel**: La app móvil descarga las imágenes directamente desde `https://mecanimovil.cl`
4. **Caché automático**: React Native cachea automáticamente las imágenes descargadas

## 📝 Resumen

✅ **Todo está configurado correctamente:**

1. ✅ Storage backend creado (`CPanelStorage`)
2. ✅ Settings configurado para usar cPanel en producción
3. ✅ Serializer actualizado para usar URLs de cPanel
4. ✅ Modelo configurado con `upload_to='vehiculos/'`
5. ✅ Variables de entorno documentadas

**El flujo completo funciona así:**
- Usuario sube foto → Django recibe → CPanelStorage sube a cPanel vía FTP → BD guarda referencia → Serializer construye URL de cPanel → App recibe URL → App descarga desde cPanel

¡Todo listo! 🎉
