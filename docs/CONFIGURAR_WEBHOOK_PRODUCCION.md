# 🔗 Configurar Webhook de Mercado Pago en Producción

Esta guía te explica cómo configurar el webhook de Mercado Pago ahora que estás en producción en Render.

---

## 📍 Paso 1: Obtener la URL de tu API en Render

1. Ve a [Render Dashboard](https://dashboard.render.com)
2. Haz clic en el servicio **`mecanimovil-api`**
3. En la parte superior verás la URL de tu API, algo como:
   ```
   https://mecanimovil-api.onrender.com
   ```
4. **Copia esa URL completa**

---

## 🔗 Paso 2: Construir la URL del Webhook

Tu endpoint de webhook es:
```
/api/mercadopago/webhook/
```

**URL completa del webhook:**
```
https://mecanimovil-api.onrender.com/api/mercadopago/webhook/
```

*(Reemplaza `mecanimovil-api.onrender.com` con la URL real de tu servicio)*

---

## ⚙️ Paso 3: Configurar en Mercado Pago

### 3.1 Acceder a Webhooks

1. Ve a [Mercado Pago Developers](https://www.mercadopago.com.ar/developers)
2. Inicia sesión con tu cuenta
3. Ve a **"Tus integraciones"**
4. Selecciona tu aplicación
5. Ve a **"Webhooks"** en el menú lateral

### 3.2 Agregar el Webhook

1. Haz clic en **"Configurar webhooks"** o **"Agregar webhook"**
2. En el campo **"URL"**, pega la URL completa:
   ```
   https://mecanimovil-api.onrender.com/api/mercadopago/webhook/
   ```
3. En **"Eventos"**, selecciona:
   - ✅ **Pagos** (payments)
   - ✅ **Pagos aprobados** (approved)
   - ✅ **Pagos rechazados** (rejected)
   - ✅ **Pagos pendientes** (pending)
   - ✅ **Pagos cancelados** (cancelled)

4. Haz clic en **"Guardar"** o **"Crear webhook"**

### 3.3 Obtener el Webhook Secret

Después de crear el webhook:

1. En la lista de webhooks, busca el que acabas de crear
2. Haz clic en **"Ver detalles"** o el ícono de configuración
3. Verás el **"Secret"** o **"Webhook Secret"**
4. **Copia ese secret** - lo necesitarás para configurarlo en Render

---

## 🔐 Paso 4: Configurar el Secret en Render

1. Ve a Render Dashboard → **`mecanimovil-api`**
2. Ve a **"Environment"**
3. Agrega o actualiza esta variable:

```
Key: MERCADOPAGO_WEBHOOK_SECRET
Value: [el secret que copiaste de Mercado Pago]
```

4. Haz clic en **"Save Changes"**
5. Espera 1-2 minutos a que el servicio se reinicie

---

## ✅ Paso 5: Verificar que Funciona

### 5.1 Probar el Webhook

1. En Mercado Pago, en la configuración del webhook, busca la opción **"Probar webhook"** o **"Test"**
2. Haz clic en probar
3. Ve a los logs de Render:
   - Render Dashboard → `mecanimovil-api` → **"Logs"**
   - Deberías ver algo como:
     ```
     📨 Webhook recibido de Mercado Pago
     ✅ Firma del webhook verificada correctamente
     ```

### 5.2 Verificar en los Logs

Si el webhook funciona correctamente, verás en los logs:
- ✅ `📨 Webhook recibido de Mercado Pago`
- ✅ `✅ Firma del webhook verificada correctamente`
- ✅ `✅ Webhook procesado exitosamente`

Si hay errores, verás:
- ❌ `⚠️ Webhook: firma no válida`
- ❌ `❌ Error procesando webhook`

---

## 🔄 Diferencia entre Desarrollo y Producción

### Desarrollo (con ngrok):
```
https://xxxx-xxx-xxx-xxx.ngrok.io/api/mercadopago/webhook/
```
- URL temporal que cambia cada vez que reinicias ngrok
- Solo funciona mientras ngrok está corriendo
- Para pruebas locales

### Producción (Render):
```
https://mecanimovil-api.onrender.com/api/mercadopago/webhook/
```
- URL permanente y estable
- Siempre disponible
- Para producción real

---

## 📋 Checklist

- [ ] Tengo la URL de mi API en Render
- [ ] Construí la URL completa del webhook: `https://[mi-api].onrender.com/api/mercadopago/webhook/`
- [ ] Configuré el webhook en Mercado Pago con esa URL
- [ ] Seleccioné los eventos correctos (pagos, aprobados, rechazados, etc.)
- [ ] Obtuve el Webhook Secret de Mercado Pago
- [ ] Configuré `MERCADOPAGO_WEBHOOK_SECRET` en Render
- [ ] Probé el webhook y verifiqué los logs

---

## ⚠️ Errores Comunes

### Error: "Webhook no responde"
**Solución:**
1. Verifica que la URL sea exactamente: `https://[tu-api].onrender.com/api/mercadopago/webhook/`
2. Asegúrate de que el servicio `mecanimovil-api` esté en estado "Live"
3. Verifica que no haya errores en los logs

### Error: "Firma no válida"
**Solución:**
1. Verifica que `MERCADOPAGO_WEBHOOK_SECRET` esté configurado correctamente en Render
2. Asegúrate de que el secret sea el mismo que te muestra Mercado Pago
3. No debe tener espacios al inicio o final

### Error: "404 Not Found"
**Solución:**
1. Verifica que la URL termine en `/api/mercadopago/webhook/` (con la barra final)
2. Asegúrate de que el servicio esté desplegado correctamente
3. Verifica que las rutas estén configuradas en `urls.py`

---

## 🎯 URLs de Webhook Adicionales

Si también usas webhooks para créditos/suscripciones, el endpoint es:

```
https://mecanimovil-api.onrender.com/api/suscripciones/creditos/compras/webhook-mp/
```

Configúralo de la misma manera en Mercado Pago si lo necesitas.

---

## 📞 ¿Necesitas Ayuda?

Si el webhook no funciona:
1. Revisa los logs de `mecanimovil-api` en Render
2. Verifica que la URL sea exacta (sin espacios, con https://)
3. Asegúrate de que el Webhook Secret esté configurado
4. Prueba el webhook desde Mercado Pago y revisa la respuesta
