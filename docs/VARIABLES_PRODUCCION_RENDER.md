# 🔐 Variables de Entorno para Producción - Render

Esta guía lista **TODAS** las variables de entorno que necesitas configurar en Render para producción.

## 📍 Dónde Configurar

1. Ve a [Render Dashboard](https://dashboard.render.com)
2. Haz clic en el servicio **`mecanimovil-api`**
3. Ve a **"Environment"** en el menú lateral
4. Haz clic en **"Add Environment Variable"** para cada una

---

## ✅ Variables OBLIGATORIAS para Producción

### 🔑 Mercado Pago (Producción)

Estas son las variables más importantes para que los pagos funcionen:

```
Key: MERCADOPAGO_MODE
Value: production
```
⚠️ **IMPORTANTE:** Debe ser `production`, NO `test`

```
Key: MERCADOPAGO_ACCESS_TOKEN
Value: APP_USR-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
💡 **Dónde obtenerlo:** 
- Ve a tu cuenta de Mercado Pago
- Credenciales → Producción → Access Token

```
Key: MERCADOPAGO_WEBHOOK_SECRET
Value: tu-webhook-secret-aqui
```
💡 **Dónde obtenerlo:**
- Mercado Pago → Webhooks → Configuración → Secret

```
Key: MERCADOPAGO_PUBLIC_KEY_PROD
Value: APP_USR_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
💡 **Dónde obtenerlo:**
- Mercado Pago → Credenciales → Producción → Public Key

```
Key: MERCADOPAGO_CLIENT_ID
Value: xxxxxxxxxxxxxxxx
```
⚠️ **CRÍTICO:** Necesario para OAuth de proveedores (conexión de cuentas)
💡 **Dónde obtenerlo:**
- Mercado Pago → Tus integraciones → Tu aplicación → Credenciales de producción → Client ID
- O en Credenciales → OAuth → Client ID

```
Key: MERCADOPAGO_CLIENT_SECRET
Value: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
⚠️ **CRÍTICO:** Necesario para OAuth de proveedores (conexión de cuentas)
💡 **Dónde obtenerlo:**
- Mercado Pago → Tus integraciones → Tu aplicación → Credenciales de producción → Client Secret
- O en Credenciales → OAuth → Client Secret

```
Key: MERCADOPAGO_REDIRECT_URI
Value: https://mecanimovil-api.onrender.com/api/mercadopago/cuenta-proveedor/callback-oauth/
```
⚠️ **IMPORTANTE:** Esta URL debe coincidir EXACTAMENTE con la configurada en Mercado Pago
💡 **Configurar en Mercado Pago:**
- Mercado Pago → Tus integraciones → Tu aplicación → OAuth → Redirect URIs
- Agregar: `https://mecanimovil-api.onrender.com/api/mercadopago/cuenta-proveedor/callback-oauth/`

---

### 🌐 CORS (Permitir tu Frontend)

```
Key: CORS_ALLOWED_ORIGINS
Value: https://tu-dominio.com,https://www.tu-dominio.com,https://app.tu-dominio.com
```

**Ejemplo si tu app está en:**
- `https://mecanimovil.com` y `https://app.mecanimovil.com`

```
Key: CORS_ALLOWED_ORIGINS
Value: https://mecanimovil.com,https://www.mecanimovil.com,https://app.mecanimovil.com
```

⚠️ **IMPORTANTE:** 
- Separa múltiples URLs con comas
- NO dejes espacios después de las comas
- Usa `https://` (no `http://`)

---

### 📧 Email (Opcional pero Recomendado)

Si quieres enviar emails desde tu aplicación:

```
Key: EMAIL_HOST
Value: smtp.gmail.com
```
*(O el servidor SMTP que uses)*

```
Key: EMAIL_PORT
Value: 587
```

```
Key: EMAIL_HOST_USER
Value: tu-email@gmail.com
```

```
Key: EMAIL_HOST_PASSWORD
Value: tu-app-password-de-gmail
```
💡 **Nota:** Si usas Gmail, necesitas una "App Password", no tu contraseña normal.

```
Key: DEFAULT_FROM_EMAIL
Value: noreply@mecanimovil.com
```
*(O el email desde el cual quieres enviar)*

---

### 👤 Superusuario (Opcional)

Si quieres crear un usuario administrador automáticamente:

```
Key: DJANGO_SUPERUSER_USERNAME
Value: admin
```

```
Key: DJANGO_SUPERUSER_EMAIL
Value: admin@mecanimovil.com
```

```
Key: DJANGO_SUPERUSER_PASSWORD
Value: tu-password-super-seguro-aqui
```
⚠️ **IMPORTANTE:** Usa una contraseña fuerte (mínimo 12 caracteres, con mayúsculas, minúsculas, números y símbolos)

---

## 🔄 Variables que YA están Configuradas

Estas variables se configuran automáticamente desde el Blueprint (`render.yaml`), **NO necesitas agregarlas manualmente:**

- ✅ `DATABASE_URL` - Se conecta automáticamente a `mecanimovil-db`
- ✅ `REDIS_URL` - Se conecta automáticamente a `mecanimovil-redis`
- ✅ `SECRET_KEY` - Se genera automáticamente
- ✅ `DJANGO_SETTINGS_MODULE` - Ya está en `mecanimovilapp.settings_production`
- ✅ `DEBUG` - Ya está en `False`
- ✅ `ALLOWED_HOSTS` - Ya incluye `.onrender.com`

---

## 📋 Checklist de Configuración

Marca cada variable después de configurarla:

### Mercado Pago:
- [ ] `MERCADOPAGO_MODE` = `production`
- [ ] `MERCADOPAGO_ACCESS_TOKEN` = Token de producción
- [ ] `MERCADOPAGO_WEBHOOK_SECRET` = Secret de webhook
- [ ] `MERCADOPAGO_PUBLIC_KEY_PROD` = Public key de producción
- [ ] `MERCADOPAGO_CLIENT_ID` = Client ID de producción (OAuth)
- [ ] `MERCADOPAGO_CLIENT_SECRET` = Client Secret de producción (OAuth)
- [ ] `MERCADOPAGO_REDIRECT_URI` = URL de callback OAuth

### CORS:
- [ ] `CORS_ALLOWED_ORIGINS` = URLs de tu frontend (separadas por comas)

### Email (Opcional):
- [ ] `EMAIL_HOST` = Servidor SMTP
- [ ] `EMAIL_PORT` = Puerto (587 para Gmail)
- [ ] `EMAIL_HOST_USER` = Tu email
- [ ] `EMAIL_HOST_PASSWORD` = App password
- [ ] `DEFAULT_FROM_EMAIL` = Email remitente

### Superusuario (Opcional):
- [ ] `DJANGO_SUPERUSER_USERNAME` = Usuario admin
- [ ] `DJANGO_SUPERUSER_EMAIL` = Email admin
- [ ] `DJANGO_SUPERUSER_PASSWORD` = Password seguro

---

## 🚀 Después de Configurar

1. **Guarda cada variable** haciendo clic en "Save Changes"
2. **Espera** a que el servicio se reinicie (toma 1-2 minutos)
3. **Verifica los logs** para asegurarte de que no hay errores:
   - Ve a `mecanimovil-api` → "Logs"
   - Busca errores relacionados con las variables

---

## ⚠️ Errores Comunes

### Error: "MERCADOPAGO_ACCESS_TOKEN is required"
**Solución:** Asegúrate de que `MERCADOPAGO_ACCESS_TOKEN` esté configurada y sea el token de **producción**, no de test.

### Error: CORS bloqueando peticiones
**Solución:** 
1. Verifica que `CORS_ALLOWED_ORIGINS` tenga la URL exacta de tu frontend
2. Asegúrate de usar `https://` (no `http://`)
3. No dejes espacios en la lista de URLs

### Error: Email no se envía
**Solución:**
1. Si usas Gmail, asegúrate de usar una "App Password", no tu contraseña normal
2. Verifica que `EMAIL_HOST_USER` y `EMAIL_HOST_PASSWORD` estén correctos
3. Revisa que `EMAIL_PORT` sea 587 (para TLS)

---

## 🔒 Seguridad

### ❌ NUNCA hagas esto:
- Subir variables de entorno a GitHub
- Compartir tokens o secrets públicamente
- Usar tokens de test en producción
- Dejar variables vacías si son obligatorias

### ✅ SIEMPRE haz esto:
- Usa tokens de **producción** de Mercado Pago
- Mantén tus secrets seguros
- Revisa los logs después de configurar variables
- Usa contraseñas fuertes para el superusuario

---

## 📞 Obtener Credenciales de Mercado Pago

### Paso 1: Acceder a Mercado Pago
1. Ve a [https://www.mercadopago.com.ar/developers](https://www.mercadopago.com.ar/developers)
2. Inicia sesión con tu cuenta

### Paso 2: Ir a Credenciales
1. Ve a "Tus integraciones"
2. Selecciona tu aplicación
3. Ve a "Credenciales de producción"

### Paso 3: Copiar las Credenciales Básicas
- **Access Token:** Lo verás como `APP_USR-xxxxx`
- **Public Key:** Lo verás como `APP_USR_xxxxx`
- **Webhook Secret:** Ve a "Webhooks" → Configuración

### Paso 4: Obtener Credenciales OAuth (para conexión de proveedores)
1. En "Tus integraciones" → Tu aplicación
2. Ve a la sección **"OAuth"** o **"Credenciales OAuth"**
3. Copia:
   - **Client ID:** Número de varios dígitos (ej: `8184034701037196`)
   - **Client Secret:** String alfanumérico largo (ej: `WavGFX03hEGVknKgQsdZ1WYRBA6WJV6u`)
4. **Configurar Redirect URI:**
   - En la misma sección OAuth, agrega la URL de callback:
   - `https://mecanimovil-api.onrender.com/api/mercadopago/cuenta-proveedor/callback-oauth/`
   - ⚠️ **IMPORTANTE:** La URL debe coincidir EXACTAMENTE (incluyendo la barra final `/`)

---

## ✅ Verificación Final

Después de configurar todo, verifica:

1. **Los servicios están "Live"** ✅
2. **No hay errores en los logs** ✅
3. **Puedes hacer peticiones a la API** ✅
4. **Los pagos funcionan** (si ya probaste) ✅

---

## 🆘 ¿Necesitas Ayuda?

Si algo no funciona:
1. Revisa los logs de `mecanimovil-api`
2. Verifica que todas las variables estén configuradas
3. Asegúrate de usar credenciales de **producción**, no de test
4. Revisa que las URLs de CORS sean exactas
