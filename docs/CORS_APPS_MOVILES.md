# 📱 Configurar CORS y Seguridad para Apps Móviles en Render

Esta guía explica cómo configurar CORS y seguridad para que tus aplicaciones móviles (Expo, React Native, APK) puedan comunicarse con tu API en Render.

---

## 🤔 ¿CORS afecta a las Apps Móviles?

### Respuesta Corta:
**CORS es principalmente para navegadores web.** Las apps móviles nativas hacen peticiones HTTP directas y **NO están sujetas a CORS** de la misma manera.

### Sin embargo:
- **Expo Go** puede tener restricciones similares a CORS
- **WebViews** dentro de apps móviles sí están sujetas a CORS
- Es mejor configurarlo correctamente para evitar problemas

---

## ✅ Configuración Recomendada para Apps Móviles

### Opción 1: Permitir Todos los Orígenes (Recomendado para Apps Móviles)

Para apps móviles, la mejor práctica es permitir todos los orígenes porque:
- Las apps no tienen una URL fija
- Pueden ejecutarse desde Expo Go, APK, o stores
- No representan el mismo riesgo de seguridad que un sitio web público

**Configuración en Render:**

1. Ve a Render Dashboard → `mecanimovil-api` → **Environment**
2. Agrega o actualiza esta variable:

```
Key: CORS_ALLOW_ALL_ORIGINS
Value: True
```

**O si prefieres mantener control, usa:**

```
Key: CORS_ALLOWED_ORIGINS
Value: *
```

### Opción 2: Configuración Específica (Más Segura)

Si quieres ser más específico, puedes configurar:

```
Key: CORS_ALLOWED_ORIGINS
Value: exp://*,http://localhost:*,https://localhost:*
```

Esto permite:
- Conexiones desde Expo (`exp://`)
- Conexiones desde localhost (para desarrollo)
- Pero necesitarías actualizar la lista cuando publiques en stores

---

## 🔧 Modificar el Código para Apps Móviles

Necesitamos actualizar `settings_production.py` para que funcione mejor con apps móviles:

### Cambio Necesario:

El archivo actual tiene:
```python
CORS_ALLOW_ALL_ORIGINS = False
```

Necesitamos cambiarlo para que respete la variable de entorno:

```python
CORS_ALLOW_ALL_ORIGINS = os.environ.get('CORS_ALLOW_ALL_ORIGINS', 'False').lower() == 'true'
```

---

## 📋 Configuración Completa en Render

### Variables de Entorno Necesarias:

#### 1. CORS para Apps Móviles:

```
Key: CORS_ALLOW_ALL_ORIGINS
Value: True
```

**O si prefieres ser más específico:**

```
Key: CORS_ALLOWED_ORIGINS
Value: exp://*,http://localhost:*,https://localhost:*,file://*
```

#### 2. ALLOWED_HOSTS (Importante):

```
Key: ALLOWED_HOSTS
Value: .onrender.com,mecanimovil-api.onrender.com
```

*(Render ya agrega automáticamente el hostname, pero puedes especificar dominios adicionales)*

---

## 🛠️ Actualizar settings_production.py

Necesitamos modificar el archivo para que respete la variable `CORS_ALLOW_ALL_ORIGINS`:

**Cambio en `mecanimovilapp/settings_production.py`:**

```python
# ANTES:
CORS_ALLOW_ALL_ORIGINS = False

# DESPUÉS:
CORS_ALLOW_ALL_ORIGINS = os.environ.get('CORS_ALLOW_ALL_ORIGINS', 'False').lower() == 'true'
```

Esto permite que puedas controlar CORS desde Render sin cambiar código.

---

## 🔐 Seguridad para Apps Móviles

### ¿Es Seguro Permitir Todos los Orígenes?

**Para apps móviles, SÍ es seguro porque:**

1. **Las apps móviles no son navegadores web**
   - No pueden ser explotadas por sitios maliciosos
   - Las peticiones vienen directamente de la app instalada

2. **Autenticación por Token**
   - Tu API usa JWT/tokens para autenticación
   - El origen no determina quién puede acceder
   - La seguridad está en los tokens, no en CORS

3. **Rate Limiting**
   - Puedes implementar límites de peticiones por IP/token
   - Esto protege contra abuso

### Buenas Prácticas:

✅ **Permitir todos los orígenes para apps móviles**
✅ **Usar autenticación por token (JWT)**
✅ **Implementar rate limiting**
✅ **Usar HTTPS siempre**
✅ **Validar tokens en cada petición**

❌ **NO confiar solo en CORS para seguridad**
❌ **NO exponer endpoints sensibles sin autenticación**

---

## 📱 Configuración por Tipo de App

### Expo Go (Desarrollo):
```
CORS_ALLOW_ALL_ORIGINS = True
```
O específicamente:
```
CORS_ALLOWED_ORIGINS = exp://*
```

### APK (Producción):
```
CORS_ALLOW_ALL_ORIGINS = True
```
Las apps nativas no necesitan CORS específico.

### App Store / Play Store:
```
CORS_ALLOW_ALL_ORIGINS = True
```
Misma configuración que APK.

---

## 🚀 Pasos para Configurar en Render

### Paso 1: Actualizar el Código

1. Modifica `settings_production.py` para usar la variable de entorno
2. Haz commit y push:
   ```bash
   git add mecanimovilapp/settings_production.py
   git commit -m "feat: Allow CORS configuration via environment variable"
   git push
   ```

### Paso 2: Configurar en Render

1. Ve a Render Dashboard → `mecanimovil-api` → **Environment**
2. Agrega:
   ```
   Key: CORS_ALLOW_ALL_ORIGINS
   Value: True
   ```
3. Haz clic en **"Save Changes"**
4. Espera 1-2 minutos a que se reinicie

### Paso 3: Verificar

1. Desde tu app móvil, haz una petición a la API
2. Debería funcionar sin errores de CORS
3. Revisa los logs en Render si hay problemas

---

## 🧪 Probar la Configuración

### Desde tu App Móvil:

```javascript
// En tu app React Native/Expo
const API_URL = 'https://mecanimovil-api.onrender.com';

fetch(`${API_URL}/api/hello/`, {
  method: 'GET',
  headers: {
    'Content-Type': 'application/json',
  },
})
  .then(response => response.json())
  .then(data => console.log('✅ Funciona:', data))
  .catch(error => console.error('❌ Error:', error));
```

### Desde el Navegador (para debug):

Abre la consola del navegador y ejecuta:
```javascript
fetch('https://mecanimovil-api.onrender.com/api/hello/')
  .then(r => r.json())
  .then(console.log)
  .catch(console.error);
```

Si `CORS_ALLOW_ALL_ORIGINS = True`, debería funcionar desde cualquier origen.

---

## ⚠️ Errores Comunes

### Error: "CORS policy: No 'Access-Control-Allow-Origin' header"
**Solución:**
1. Verifica que `CORS_ALLOW_ALL_ORIGINS = True` esté configurado
2. Asegúrate de que el código esté actualizado en Render
3. Espera a que el servicio se reinicie

### Error: "Network request failed" (en app móvil)
**Solución:**
1. Verifica que la URL de la API sea correcta
2. Asegúrate de usar `https://` (no `http://`)
3. Verifica que el servicio esté "Live" en Render
4. Revisa los logs de Render para ver si hay errores del servidor

### Error: "DisallowedHost" en los logs
**Solución:**
1. Configura `ALLOWED_HOSTS` en Render:
   ```
   Key: ALLOWED_HOSTS
   Value: .onrender.com
   ```
2. Render ya agrega automáticamente el hostname, pero puedes especificar más

---

## 📊 Comparación de Configuraciones

| Configuración | Uso | Seguridad |
|--------------|-----|-----------|
| `CORS_ALLOW_ALL_ORIGINS = True` | Apps móviles | ✅ Seguro con autenticación |
| `CORS_ALLOWED_ORIGINS = ['exp://*']` | Solo Expo Go | ✅ Más restrictivo |
| `CORS_ALLOW_ALL_ORIGINS = False` | Solo web específica | ✅ Más seguro para web |

**Para apps móviles, recomendamos:** `CORS_ALLOW_ALL_ORIGINS = True`

---

## ✅ Checklist Final

- [ ] Código actualizado para usar variable de entorno `CORS_ALLOW_ALL_ORIGINS`
- [ ] Variable `CORS_ALLOW_ALL_ORIGINS = True` configurada en Render
- [ ] `ALLOWED_HOSTS` configurado correctamente
- [ ] Código pusheado y desplegado en Render
- [ ] Probado desde la app móvil
- [ ] Sin errores de CORS en los logs

---

## 🎯 Resumen

**Para apps móviles:**
1. ✅ Permite todos los orígenes (`CORS_ALLOW_ALL_ORIGINS = True`)
2. ✅ La seguridad está en los tokens, no en CORS
3. ✅ Configura desde Render con variables de entorno
4. ✅ Usa HTTPS siempre
5. ✅ Implementa autenticación por token

**No necesitas:**
- ❌ URLs específicas de Expo Go
- ❌ URLs de Play Store/App Store
- ❌ Configuraciones complejas de CORS

---

## 🆘 ¿Necesitas Ayuda?

Si sigues teniendo problemas:
1. Revisa los logs de `mecanimovil-api` en Render
2. Verifica que las variables de entorno estén configuradas
3. Asegúrate de que el código esté actualizado
4. Prueba desde diferentes dispositivos/entornos
