# 📧 Configuración de Email en Render - Recuperación de Contraseña

Esta guía explica cómo configurar el envío de emails desde Render para que funcione la recuperación de contraseña.

## ⚠️ Problema Actual

Si intentas recuperar tu contraseña y **no recibes el email**, es porque las variables de entorno de email **no están configuradas** en Render.

## 🔧 Solución: Configurar Variables de Entorno en Render

### Paso 1: Ir a Render Dashboard

1. Ve a [https://dashboard.render.com](https://dashboard.render.com)
2. Haz clic en el servicio **`mecanimovil-api`**
3. En el menú lateral, haz clic en **"Environment"**

### Paso 2: Agregar Variables de Email

Agrega las siguientes variables de entorno (haz clic en **"Add Environment Variable"** para cada una):

#### 1. EMAIL_HOST
```
Key: EMAIL_HOST
Value: smtp.gmail.com
```
💡 **Nota:** Este es el servidor SMTP de Gmail. Si usas otro proveedor (Outlook, SendGrid, etc.), cambia este valor.

#### 2. EMAIL_PORT
```
Key: EMAIL_PORT
Value: 587
```
💡 **Nota:** Puerto 587 es para TLS (recomendado). Si usas SSL, usa puerto 465.

#### 3. EMAIL_HOST_USER
```
Key: EMAIL_HOST_USER
Value: tu-email@gmail.com
```
💡 **Nota:** Reemplaza `tu-email@gmail.com` con tu dirección de email de Gmail.

#### 4. EMAIL_HOST_PASSWORD
```
Key: EMAIL_HOST_PASSWORD
Value: tu-app-password-de-gmail
```
⚠️ **IMPORTANTE:** 
- **NO uses tu contraseña normal de Gmail**
- Debes usar una **"App Password"** (Contraseña de aplicación)
- Ver instrucciones abajo para obtenerla

#### 5. DEFAULT_FROM_EMAIL
```
Key: DEFAULT_FROM_EMAIL
Value: noreply@mecanimovil.com
```
💡 **Nota:** Este es el email que aparecerá como remitente. Puede ser el mismo que `EMAIL_HOST_USER` o uno diferente.

---

## 🔑 Cómo Obtener una App Password de Gmail

### Paso 1: Activar Verificación en 2 Pasos

1. Ve a tu [Cuenta de Google](https://myaccount.google.com/security)
2. Busca **"Verificación en 2 pasos"**
3. Actívala si no está activada (es obligatorio para App Passwords)

### Paso 2: Generar App Password

1. Ve a [App Passwords de Google](https://myaccount.google.com/apppasswords)
2. Si no la ves, ve a: **Seguridad** → **Verificación en 2 pasos** → **Contraseñas de aplicaciones**
3. Selecciona **"App"**: `Correo`
4. Selecciona **"Device"**: `Otro (nombre personalizado)`
5. Escribe: `MecaniMovil API`
6. Haz clic en **"Generar"**
7. **Copia la contraseña** que aparece (16 caracteres sin espacios)
8. Úsala como valor de `EMAIL_HOST_PASSWORD` en Render

💡 **Ejemplo:** La contraseña se verá así: `abcd efgh ijkl mnop` → Úsala como `abcdefghijklmnop` (sin espacios)

---

## ✅ Verificar que Funciona

### Paso 1: Guardar las Variables

1. Después de agregar cada variable, haz clic en **"Save Changes"**
2. Render reiniciará automáticamente el servicio (toma 1-2 minutos)

### Paso 2: Probar Recuperación de Contraseña

1. Ve a la app y haz clic en **"¿Olvidaste tu contraseña?"**
2. Ingresa tu email
3. Si está configurado correctamente, deberías recibir el email en 1-2 minutos

### Paso 3: Revisar los Logs

1. Ve a `mecanimovil-api` → **"Logs"** en Render
2. Busca mensajes como:
   - ✅ `"Email de recuperación enviado exitosamente a ..."` → **Funciona correctamente**
   - ❌ `"EMAIL_HOST_USER o EMAIL_HOST_PASSWORD no están configurados"` → **Falta configurar variables**
   - ❌ `"Error enviando email de recuperación"` → **Revisa las credenciales**

---

## 🔍 Troubleshooting

### Problema: "EMAIL_HOST_USER o EMAIL_HOST_PASSWORD no están configurados"

**Solución:**
- Verifica que ambas variables estén agregadas en Render
- Asegúrate de que los valores no estén vacíos
- Haz clic en "Save Changes" después de agregar cada variable

### Problema: "Error enviando email de recuperación"

**Solución:**
1. Verifica que `EMAIL_HOST_USER` sea tu email completo (ej: `tuemail@gmail.com`)
2. Verifica que `EMAIL_HOST_PASSWORD` sea una **App Password**, no tu contraseña normal
3. Asegúrate de que la verificación en 2 pasos esté activada en Gmail
4. Verifica que `EMAIL_PORT` sea `587` (para TLS)

### Problema: No recibo el email

**Solución:**
1. Revisa la carpeta de **"Spam"** o **"Correo no deseado"**
2. Verifica que el email que ingresaste sea el correcto
3. Revisa los logs en Render para ver si hay errores
4. Espera 2-3 minutos (a veces los emails tardan un poco)

---

## 📋 Resumen de Variables Necesarias

| Variable | Valor Ejemplo | ¿Obligatoria? |
|----------|--------------|---------------|
| `EMAIL_HOST` | `smtp.gmail.com` | ✅ Sí |
| `EMAIL_PORT` | `587` | ✅ Sí |
| `EMAIL_HOST_USER` | `tuemail@gmail.com` | ✅ Sí |
| `EMAIL_HOST_PASSWORD` | `abcdefghijklmnop` (App Password) | ✅ Sí |
| `DEFAULT_FROM_EMAIL` | `noreply@mecanimovil.com` | ✅ Sí |

---

## 🔐 Seguridad

⚠️ **IMPORTANTE:**
- **NUNCA** uses tu contraseña normal de Gmail
- **SIEMPRE** usa App Passwords para aplicaciones
- No compartas las credenciales públicamente
- Mantén las variables de entorno seguras en Render

---

## 🆘 ¿Necesitas Ayuda?

Si después de seguir estos pasos aún no funciona:
1. Revisa los logs en Render (`mecanimovil-api` → Logs)
2. Verifica que todas las variables estén correctamente escritas
3. Asegúrate de haber guardado los cambios en Render
4. Espera a que el servicio se reinicie después de agregar las variables
