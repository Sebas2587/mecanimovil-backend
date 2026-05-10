# Migración a Cloudflare R2 - Guía paso a paso

## Por qué R2 y no cPanel FTP

El problema actual es que **Render no puede conectar al FTP de cPanel** porque el firewall de cPanel (CSF/LFD) está baneando los IPs de Render. Esto produce:

```
ERROR [CPanelStorage] Error conectando a FTP: [Errno 110] Connection timed out
ERROR [CPanelStorage] Error conectando a FTP: [Errno 113] No route to host
[POST] /api/usuarios/actualizar-foto-perfil/ responseTimeMS=134679  (134 segundos!)
```

**Por qué Cloudflare R2 es la solución correcta:**

| Característica | cPanel FTP | Cloudflare R2 |
|---|---|---|
| Costo | Variable (incluido en hosting) | 10 GB gratis, $0.015/GB después |
| Egress (descargas) | Cuenta contra el ancho de banda del hosting | **GRATIS, ilimitado** |
| Velocidad de upload | 3-10s por archivo (FTP) | <500ms (HTTPS) |
| Bloqueos por firewall | Frecuente desde cloud providers | Nunca |
| Escalabilidad | Limitada | Ilimitada |
| HTTPS nativo | Requiere config SSL | Sí, automático |
| API | FTP (protocolo viejo) | S3-compatible (estándar) |
| **Privacidad/Seguridad** | URL pública = cualquiera puede ver | **Bucket privado + URLs firmadas** |

---

## Arquitectura de seguridad (modo privado por default)

Tu app maneja **datos sensibles**: cédulas, licencias, comprobantes de pago, chats privados, fotos de checklists. Por eso configuramos R2 en **MODO PRIVADO** que es el default de esta integración:

### Cómo funciona

1. El **bucket es totalmente privado** (sin acceso público desde internet).
2. Solo el backend con las credenciales puede leer/escribir archivos.
3. Cuando un usuario pide los datos de un perfil/vehículo/documento, el backend genera una **URL firmada (presigned URL)** que:
   - Incluye una firma criptográfica que solo el backend puede generar.
   - **Expira automáticamente** después de 7 días (configurable).
   - Solo es válida para ese archivo específico.
4. El cliente (app móvil) usa esa URL para descargar/mostrar la imagen.
5. Si la URL expira, basta con que el cliente vuelva a pedir los datos del modelo y obtendrá una URL fresca.

### ¿Cómo se compara con la opción pública?

| Modo | Quién puede ver | Cuándo usar |
|---|---|---|
| **PRIVADO (default)** | Solo quien tenga la URL firmada vigente, generada por el backend | Documentos sensibles, fotos de perfil, comprobantes, todo |
| Público (R2.dev) | Cualquier persona con la URL (no expira) | Solo recursos verdaderamente públicos (ej: catálogo) |

**Recomendación:** Mantén todo en PRIVADO. Es el comportamiento por defecto de esta integración. No configures `R2_PUBLIC_URL` y listo.

---

## Paso 1: Crear cuenta y bucket en Cloudflare R2

1. Ve a https://dash.cloudflare.com/sign-up y crea una cuenta gratuita (si no tienes).
2. En el dashboard de Cloudflare, ve al menú izquierdo → **R2 Object Storage**.
3. Si es la primera vez, te pedirá agregar un método de pago (no se cobra hasta superar 10 GB).
4. Click **Create bucket**:
   - **Name**: `mecanimovil-media`
   - **Location**: `Automatic` (o `Eastern North America` para latencia óptima desde Chile)
   - **Default Storage Class**: `Standard`
5. Click **Create bucket**.

---

## Paso 2: Verificar que el bucket es privado (default)

Esto es lo importante para tu caso:

1. Entra al bucket recién creado → tab **Settings**.
2. Sección **Public access** → debe estar en estado **"R2.dev subdomain: Disabled"**.
3. **NO actives** el R2.dev subdomain.
4. **NO configures** dominio custom.

Tu bucket queda 100% privado. Solo se puede acceder con credenciales (que tendrá tu backend).

---

## Paso 3: Crear API Token (Access Key/Secret)

1. En la página principal de R2 (no dentro del bucket) → click **Manage R2 API Tokens**.
2. Click **Create API Token**.
3. Configuración:
   - **Token name**: `mecanimovil-render`
   - **Permissions**: `Object Read & Write`
   - **Specify bucket(s)**: selecciona `mecanimovil-media`
   - **TTL**: `Forever`
4. Click **Create API Token**.
5. **IMPORTANTE**: Copia y guarda en lugar seguro:
   - `Access Key ID` → será `R2_ACCESS_KEY_ID`
   - `Secret Access Key` → será `R2_SECRET_ACCESS_KEY`
   - `Endpoint for S3 clients` → será `R2_ENDPOINT_URL` (formato: `https://<account_id>.r2.cloudflarestorage.com`)

⚠️ El secret solo se muestra UNA VEZ. Si lo pierdes, hay que crear otro token.

---

## Paso 4: Configurar variables de entorno en Render

1. Ve al dashboard de Render → tu servicio backend.
2. Tab **Environment** → **Add Environment Variable**.
3. Agrega estas **5 variables** (NO incluyas `R2_PUBLIC_URL` para mantener el modo privado):

```
STORAGE_TYPE=r2
R2_ACCESS_KEY_ID=<el access key del paso 3>
R2_SECRET_ACCESS_KEY=<el secret del paso 3>
R2_BUCKET_NAME=mecanimovil-media
R2_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
```

(Reemplaza con tus valores reales)

**Opcional:** ajustar tiempo de expiración de URLs firmadas (default 7 días):

```
R2_URL_EXPIRE_SECONDS=604800   # 7 días en segundos. Mínimo 60, máximo 604800 (limite de R2)
```

4. **NO BORRES** todavía las variables `CPANEL_FTP_*` y `CPANEL_MEDIA_URL` — las necesitamos para migrar las fotos viejas en el paso 6.

5. Render va a hacer redeploy automáticamente después de guardar las variables.

---

## Paso 5: Verificar que el storage R2 funciona

Una vez que el deploy termine, en los logs de Render deberías ver:

```
🔍 [Settings] Detectada configuración R2. Usando Cloudflare R2 automáticamente.
🔒 [Settings R2] Modo PRIVADO activo. URLs firmadas con expiración de 604800s (7 días).
✅ [Settings R2] Storage configurado: bucket=mecanimovil-media
```

**Test en la app:**

1. Abre la app de proveedor.
2. Cambia tu foto de perfil.
3. Debería subir en <2 segundos (en lugar de 134s con FTP).
4. La nueva URL debe verse así (con firma `?X-Amz-...` al final):
   ```
   https://<account_id>.r2.cloudflarestorage.com/mecanimovil-media/perfiles/foto.jpg?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...&X-Amz-Signature=...
   ```
5. Esa URL solo funciona durante 7 días. Después se necesita una nueva (que el backend genera automáticamente al pedir los datos del usuario otra vez).

Si la imagen se ve, todo está OK.

---

## Paso 6: Migrar las fotos existentes (opcional pero recomendado)

Las fotos viejas siguen en cPanel y se ven correctamente porque la URL absoluta apunta allá. Pero si quieres consolidar todo en R2:

### A. Probar en modo dry-run (no sube nada):

Desde el shell de Render (Dashboard → tu servicio → Shell):

```bash
python manage.py migrar_media_a_r2 --dry-run
```

Esto lista todos los archivos que migrarían, sin subirlos.

### B. Migrar de verdad:

```bash
python manage.py migrar_media_a_r2
```

El comando:
- Recorre todos los modelos con `ImageField` y `FileField`
- Descarga cada archivo desde la URL pública de cPanel (HTTP, no FTP — sí funciona)
- Lo sube a R2 manteniendo el mismo path relativo
- Salta archivos que ya existen en R2

### C. Migrar solo un modelo específico:

```bash
python manage.py migrar_media_a_r2 --model usuarios.Usuario
python manage.py migrar_media_a_r2 --model vehiculos.Vehiculo
python manage.py migrar_media_a_r2 --model servicios.FotoServicio
```

### D. Después de migrar, eliminar variables de cPanel

Una vez confirmado que todo funciona y que las fotos viejas se ven desde R2:

1. En Render → Environment → eliminar:
   - `CPANEL_FTP_HOST`
   - `CPANEL_FTP_PORT`
   - `CPANEL_FTP_USER`
   - `CPANEL_FTP_PASSWORD`
   - `CPANEL_FTP_ROOT`
   - `CPANEL_MEDIA_URL`

2. Esto previene que el código vuelva a intentar usar cPanel.

---

## Detalles técnicos del modo privado

### ¿Por qué las URLs cambian cada cierto tiempo?

Cada presigned URL incluye un timestamp dentro de la firma. Cuando el serializer genera URLs en una nueva request, el timestamp es diferente, por lo que la URL completa cambia (aunque el archivo sea el mismo).

### ¿Esto rompe el cache del cliente?

`expo-image` cachea por URL completa. Mientras la app no recargue datos del backend, las URLs se mantienen igual y el cache funciona perfecto. Al recargar, las URLs cambian, pero `expo-image` con `cachePolicy="memory-disk"` ya tiene la imagen descargada y la muestra inmediatamente mientras valida (es rápido).

### ¿Es esto seguro contra acceso no autorizado?

Sí. La firma criptográfica es generada con tu `R2_SECRET_ACCESS_KEY` (que solo el backend conoce). Sin esa clave, nadie puede generar URLs válidas. Las URLs vencidas son rechazadas por R2 automáticamente.

### ¿Puedo hacer URLs con expiración más corta para datos super sensibles?

Sí. Puedes ajustar `R2_URL_EXPIRE_SECONDS` (default 604800 = 7 días). Para documentos muy sensibles, podrías bajarlo a 3600 (1 hora) o incluso 300 (5 min). El máximo permitido por R2 es 7 días.

### ¿Y si quiero algunas cosas públicas (ej: logos de marcas) y otras privadas?

Eso requiere implementar dos backends de storage (uno público, otro privado) y asignarlos campo por campo en cada modelo. Es complejidad adicional. Por ahora, modo privado para todo es lo más simple y seguro. Si después necesitas optimizar el catálogo público, lo agregamos.

---

## Costos estimados

Con R2 free tier (10 GB de storage, 1M operaciones de escritura/mes, ilimitado download):

| Volumen | Costo mensual |
|---|---|
| < 10 GB | **$0** (free tier) |
| 50 GB | $0.60 |
| 100 GB | $1.35 |
| 500 GB | $7.35 |

Comparación: el plan más bajo de Render con disk persistent ($7/mes) ya es más caro y limitado.

---

## Troubleshooting

### "Access Denied" al subir a R2
- Verifica que el API Token tiene permisos `Object Read & Write` para el bucket.
- Verifica que `R2_BUCKET_NAME` es el nombre exacto del bucket.

### Las imágenes no cargan en la app
- Inspecciona la URL devuelta por el backend. Debe incluir `?X-Amz-Algorithm=...&X-Amz-Signature=...`.
- Si la URL apunta a `r2.cloudflarestorage.com` y tiene firma → todo OK.
- Si la URL no tiene firma → revisa que `R2_PUBLIC_URL` NO esté configurado (queremos modo privado).

### "ConnectionError" al subir
- Verifica `R2_ENDPOINT_URL` — debe ser `https://<account_id>.r2.cloudflarestorage.com` (sin el bucket name al final).

### URL firmada da "AccessDenied" o "RequestTimeTooSkewed"
- Tu reloj de servidor está desincronizado (raro en Render). Las firmas S3v4 incluyen timestamp y son sensibles a esto.

### El comando de migración falla con 404
- Algunas fotos viejas pueden ya no existir en cPanel. El script las marca como skipped y continúa.

### "SignatureDoesNotMatch" al firmar
- Verifica que `R2_SECRET_ACCESS_KEY` está copiado completo, sin espacios extras.

---

## Resumen rápido

```
[Bucket R2 PRIVADO]
       ↑
       │ Backend Django con credenciales R2
       │ Genera presigned URLs cada vez que serializa un modelo
       ↓
[App móvil]
       │ Recibe URL firmada con expiración 7 días
       │ Carga imagen vía HTTPS (firma incluida en query string)
       │ R2 valida la firma y entrega el archivo
```

Ningún archivo es accesible públicamente. Solo el backend puede generar URLs válidas. Las URLs expiran automáticamente. Los documentos sensibles están protegidos.
