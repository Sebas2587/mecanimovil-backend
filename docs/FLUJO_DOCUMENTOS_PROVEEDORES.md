# 📄 Flujo de Almacenamiento de Documentos de Proveedores

Este documento explica cómo funciona el proceso completo cuando un proveedor (taller o mecánico) sube documentos (fotos, PDFs) durante el onboarding.

## 🔄 Flujo Completo

### 1. Proveedor sube documento desde la app móvil

```
App Móvil de Proveedores → POST /api/usuarios/documentos-onboarding/ (con archivo en FormData)
```

**Formato del FormData:**
```javascript
const formData = new FormData();
formData.append('tipo_documento', 'dni_frontal'); // Tipo de documento
formData.append('archivo', {
  uri: archivo.uri,           // URI del archivo en el dispositivo
  type: 'image/jpeg',         // Tipo MIME (image/jpeg, image/png, application/pdf)
  name: 'documento.jpg'       // Nombre del archivo
});
```

### 2. Django recibe la petición

- El `DocumentoOnboardingViewSet` recibe la petición con el archivo
- Django procesa el archivo usando el `FileField` del modelo `DocumentoOnboarding`
- El archivo puede ser:
  - **Imagen**: JPG, PNG
  - **Documento**: PDF

### 3. Storage backend guarda el archivo

Cuando `STORAGE_TYPE=cpanel` en producción:

1. **Django llama al método `_save()` del `CPanelStorage`**
   - El archivo se guarda temporalmente en disco local
   - Se establece conexión FTP con cPanel
   - Se crean los directorios necesarios si no existen
   - El archivo se sube vía FTP a: `public_html/images/mecanimovil-app-media/documentos_onboarding/documento_xxx.jpg` (o `.pdf`)
   - El archivo temporal se elimina

2. **Django guarda la referencia en la BD**
   - El campo `archivo` en la tabla `documentos_onboarding` almacena: `documentos_onboarding/documento_xxx.jpg`
   - Esta es la ruta relativa, no la URL completa
   - El campo `nombre_original` almacena el nombre original del archivo

### 4. Serializer construye la URL para la respuesta

Cuando el serializer necesita devolver la URL del documento:

1. **El serializer llama a `get_archivo_url()`**
2. **Usa la función helper `get_image_url()`** (que funciona para cualquier archivo)
3. **Verifica el tipo de storage:**
   - Si `STORAGE_TYPE=cpanel` o `s3`: Usa `obj.archivo.url` directamente
   - Si `STORAGE_TYPE=local`: Construye URL con `request.build_absolute_uri()`

4. **El método `url()` del `CPanelStorage` se ejecuta:**
   - Recibe: `documentos_onboarding/documento_xxx.jpg` (nombre relativo)
   - Construye: `https://mecanimovil.cl/images/mecanimovil-app-media/documentos_onboarding/documento_xxx.jpg`
   - Retorna la URL completa

### 5. App móvil recibe la URL

- La app recibe la URL completa de cPanel
- React Native puede descargar/previsualizar el documento desde cPanel
- Para imágenes: Se muestran directamente
- Para PDFs: Se puede abrir con un visor de PDF

### 6. Django Admin puede ver los documentos

- El admin de Django accede a los documentos usando `obj.archivo.url`
- El `CPanelStorage` construye la URL completa automáticamente
- Las imágenes se muestran como vista previa
- Los PDFs se muestran como enlace para descargar/ver

## 📁 Estructura de Directorios en cPanel

```
public_html/
└── images/
    └── mecanimovil-app-media/
        ├── vehiculos/
        │   ├── vehicle_1768274172390.jpg
        │   └── ...
        ├── documentos_onboarding/          ← DOCUMENTOS DE PROVEEDORES
        │   ├── documento_1768274172390.jpg  (DNI frontal)
        │   ├── documento_1768274172391.pdf  (RUT fiscal)
        │   ├── documento_1768274172392.jpg  (Foto fachada)
        │   └── ...
        ├── servicios_photos/
        │   └── ...
        └── checklist_photos/
            └── ...
```

## 🔍 Referencias en la Base de Datos

El campo `archivo` en la tabla `documentos_onboarding` almacena solo la ruta relativa:

```sql
-- Ejemplo de registro en la BD
id | tipo_documento | archivo                                    | nombre_original
1  | dni_frontal    | documentos_onboarding/documento_123.jpg    | DNI_FRONTAL.jpg
2  | rut_fiscal     | documentos_onboarding/documento_124.pdf    | RUT_FISCAL.pdf
3  | foto_fachada   | documentos_onboarding/documento_125.jpg    | FACHADA_TALLER.jpg
```

**NO almacena la URL completa**, eso se construye dinámicamente.

## ✅ Verificación del Flujo

### 1. Verificar que el archivo se subió a cPanel

1. Accede a cPanel → "Administrador de archivos"
2. Navega a: `public_html/images/mecanimovil-app-media/documentos_onboarding/`
3. Deberías ver los archivos de documentos (JPG, PNG, PDF)

### 2. Verificar que la URL es correcta

1. Revisa los logs de Render después de subir un documento:
   ```
   ✅ [CPanelStorage] Archivo subido: public_html/images/mecanimovil-app-media/documentos_onboarding/documento_xxx.jpg
   📄 [DocumentoOnboardingSerializer] Documento X - URL desde storage (cpanel): https://mecanimovil.cl/images/mecanimovil-app-media/documentos_onboarding/documento_xxx.jpg
   ```

2. Abre la URL en el navegador:
   ```
   https://mecanimovil.cl/images/mecanimovil-app-media/documentos_onboarding/documento_xxx.jpg
   ```
   Deberías ver la imagen o poder descargar el PDF

### 3. Verificar en Django Admin

1. Accede a: `https://mecanimovil-api.onrender.com/admin/usuarios/documentoonboarding/`
2. Haz clic en un documento
3. Deberías ver:
   - **Vista previa** si es imagen (se muestra la imagen)
   - **Enlace "Ver PDF"** si es PDF (se abre en nueva pestaña)
   - **Enlace "Descargar archivo"** para otros tipos

### 4. Verificar en la app móvil

1. Sube un documento desde la app de proveedores
2. Verifica que el documento se muestre correctamente
3. Revisa los logs de la app para ver la URL recibida

## 🎯 Tipos de Documentos Soportados

### Para Mecánicos:
- DNI/ID Personal (Frontal)
- DNI/ID Personal (Trasero)
- Licencia de Conducir
- Curriculum Vitae
- Certificado de Antecedentes
- Foto de Vehículo de Trabajo

### Para Talleres:
- RUT/CUIT/ID Fiscal del Negocio
- Foto de la Fachada del Taller
- Foto del Interior del Taller
- Foto de Equipos/Herramientas
- Foto de Herramientas Portátiles

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

**Estas son las mismas variables que se usan para las imágenes de vehículos.**

## 🔧 Cómo Funciona en el Código

### Modelo (Backend)

```python
class DocumentoOnboarding(models.Model):
    archivo = models.FileField(
        upload_to='documentos_onboarding/',
        validators=[validar_archivo_documento],
        help_text='Archivos permitidos: JPG, PNG, PDF (máximo 10MB)'
    )
```

**Nota:** `FileField` (no `ImageField`) porque soporta PDFs además de imágenes.

### Serializer (Backend)

```python
class DocumentoOnboardingSerializer(serializers.ModelSerializer):
    archivo_url = serializers.SerializerMethodField()
    
    def get_archivo_url(self, obj):
        """Devuelve la URL completa del archivo usando cPanel si está configurado"""
        request = self.context.get('request')
        return get_image_url(obj.archivo, request)  # Función helper que funciona para cualquier archivo
```

### Admin (Backend)

```python
def vista_previa(self, obj):
    if obj.archivo:
        if obj.es_imagen():
            return format_html(
                '<img src="{}" style="max-width: 100px; max-height: 100px;" />',
                obj.archivo.url  # CPanelStorage construye la URL automáticamente
            )
        elif obj.es_pdf():
            return format_html(
                '<a href="{}" target="_blank">📄 Ver PDF</a>',
                obj.archivo.url  # CPanelStorage construye la URL automáticamente
            )
```

### App Móvil (Frontend)

```typescript
const formData = new FormData();
formData.append('tipo_documento', tipoDocumento);
formData.append('archivo', {
  uri: archivo.uri,
  type: tipoArchivo,  // 'image/jpeg', 'image/png', 'application/pdf'
  name: nombreArchivo
});

const response = await fetch(`${baseURL}/usuarios/documentos-onboarding/`, {
  method: 'POST',
  headers: {
    'Authorization': `Token ${token}`,
    // NO incluir Content-Type - fetch lo maneja automáticamente
  },
  body: formData,
});
```

## 🚨 Puntos Importantes

1. **Render NO sirve los documentos**: Los documentos se sirven directamente desde cPanel vía HTTP
2. **Render solo sube**: Render solo actúa como intermediario para subir archivos a cPanel
3. **La app descarga desde cPanel**: La app móvil descarga los documentos directamente desde `https://mecanimovil.cl`
4. **Django Admin accede desde cPanel**: El admin de Django construye URLs de cPanel automáticamente
5. **Mismo sistema que imágenes**: Los documentos usan exactamente el mismo sistema de almacenamiento que las imágenes de vehículos

## 📝 Resumen

✅ **Todo está configurado correctamente:**

1. ✅ Storage backend creado (`CPanelStorage`) - **Ya existe y funciona**
2. ✅ Settings configurado para usar cPanel en producción - **Ya configurado**
3. ✅ Serializer actualizado para usar URLs de cPanel - **Ya implementado**
4. ✅ Modelo configurado con `upload_to='documentos_onboarding/'` - **Ya configurado**
5. ✅ Admin configurado para mostrar vista previa - **Ya implementado**
6. ✅ Variables de entorno documentadas - **Ya documentadas**

**El flujo completo funciona así:**
- Proveedor sube documento → Django recibe → CPanelStorage sube a cPanel vía FTP → BD guarda referencia → Serializer construye URL de cPanel → App recibe URL → App descarga desde cPanel → **Admin puede ver desde cPanel**

## 🔍 Verificación en Django Admin

Para verificar que los documentos se pueden ver en Django Admin:

1. **Accede al admin:**
   ```
   https://mecanimovil-api.onrender.com/admin/usuarios/documentoonboarding/
   ```

2. **Haz clic en un documento** para ver los detalles

3. **Verifica la vista previa:**
   - Si es imagen: Deberías ver una miniatura
   - Si es PDF: Deberías ver un enlace "📄 Ver PDF"

4. **Haz clic en el enlace** (para PDFs o imágenes grandes):
   - Debería abrirse en una nueva pestaña
   - La URL debería ser: `https://mecanimovil.cl/images/mecanimovil-app-media/documentos_onboarding/...`

5. **Si no se ve correctamente:**
   - Verifica que `CPANEL_MEDIA_URL` esté configurado correctamente
   - Verifica que el archivo exista en cPanel
   - Revisa los logs de Render para ver errores de FTP

## 🎯 Diferencia con Imágenes de Vehículos

| Aspecto | Imágenes de Vehículos | Documentos de Proveedores |
|---------|----------------------|---------------------------|
| **Modelo** | `ImageField` | `FileField` (soporta PDFs) |
| **Upload path** | `vehiculos/` | `documentos_onboarding/` |
| **Storage** | `CPanelStorage` | `CPanelStorage` (mismo) |
| **Serializer** | `get_foto()` | `get_archivo_url()` |
| **Helper function** | `get_image_url()` | `get_image_url()` (mismo) |
| **Admin preview** | Imagen | Imagen o enlace PDF |
| **Formato app** | FormData | FormData (mismo) |

**Conclusión:** Los documentos funcionan exactamente igual que las imágenes, solo cambia el directorio y el tipo de campo (FileField vs ImageField).

¡Todo listo! 🎉
