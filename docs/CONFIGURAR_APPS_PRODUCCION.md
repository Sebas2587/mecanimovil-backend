# 📱 Configurar Apps Móviles para Producción (Render)

Guía para configurar las aplicaciones móviles (Expo/React Native) para que se conecten al servidor en Render.

---

## 🎯 Objetivo

Configurar las apps para que:
- **En desarrollo:** Se conecten al servidor local o ngrok
- **En producción:** Se conecten a `https://mecanimovil-api.onrender.com`

---

## 📋 URL de Producción

Tu API en Render está disponible en:
```
https://mecanimovil-api.onrender.com
```

El endpoint base del API es:
```
https://mecanimovil-api.onrender.com/api
```

---

## 🔧 Configuración para App de Usuarios

### Opción 1: Usar Variable de Entorno en `app.json` (Recomendado)

Edita `mecanimovil-frontend/mecanimovil-app/app.json`:

```json
{
  "expo": {
    "extra": {
      "serverHost": null,
      "serverPort": 8000,
      "apiUrl": "https://mecanimovil-api.onrender.com/api",
      "forceLocalhost": false,
      "useNgrok": false,
      "ngrokUrl": null
    }
  }
}
```

**Cambios importantes:**
- `apiUrl`: Configura la URL completa de producción
- `useNgrok`: Desactiva ngrok en producción
- `ngrokUrl`: Déjalo en `null`

### Opción 2: Modificar `serverConfig.js` para Detectar Producción

Edita `mecanimovil-frontend/mecanimovil-app/app/config/serverConfig.js`:

Agrega detección de producción al inicio del archivo:

```javascript
// Detectar si estamos en producción
const isProduction = !__DEV__ || process.env.EXPO_PUBLIC_ENV === 'production';

// URL de producción
const PRODUCTION_API_URL = 'https://mecanimovil-api.onrender.com/api';

// En la función discoverServerURL(), agrega al inicio:
async function discoverServerURL() {
  // Si estamos en producción, usar URL de producción directamente
  if (isProduction) {
    console.log('🌐 Usando URL de producción:', PRODUCTION_API_URL);
    if (await testConnection(PRODUCTION_API_URL)) {
      return PRODUCTION_API_URL;
    }
  }
  
  // ... resto del código de detección local
}
```

---

## 🔧 Configuración para App de Proveedores

La app de proveedores ya tiene detección de producción. Verifica `mecanimovil-proveedores/mecanimovil-app-proveedores/services/serverConfig.ts`:

```typescript
// Si estamos en producción, usar URL de producción
if (this.isProduction) {
  const prodURL = process.env.EXPO_PUBLIC_PRODUCTION_API_URL || 'https://mecanimovil-api.onrender.com';
  this.baseURL = prodURL.endsWith('/api') ? prodURL : `${prodURL}/api`;
  // ...
}
```

**Para configurar:**

1. Crea un archivo `.env` en `mecanimovil-proveedores/mecanimovil-app-proveedores/`:
```bash
EXPO_PUBLIC_PRODUCTION_API_URL=https://mecanimovil-api.onrender.com
```

2. O edita `app.json`:
```json
{
  "expo": {
    "extra": {
      "productionApiUrl": "https://mecanimovil-api.onrender.com"
    }
  }
}
```

---

## 🧪 Verificar Configuración

### Paso 1: Verificar que la API Responde

```bash
# Desde tu terminal
curl https://mecanimovil-api.onrender.com/api/hello/

# Deberías ver:
# {"message":"Hello from MecaniMovil API!"}
```

### Paso 2: Verificar CORS

La API debe permitir requests desde las apps móviles. Verifica en Render:

1. Ve a `mecanimovil-api` → Environment
2. Verifica que `CORS_ALLOW_ALL_ORIGINS` esté en `True` (para apps móviles)

### Paso 3: Probar desde la App

1. **Ejecuta la app en modo producción:**
   ```bash
   cd mecanimovil-frontend/mecanimovil-app
   npx expo start --no-dev
   ```

2. **O configura para usar producción:**
   ```bash
   # En app.json, configura apiUrl
   # Luego ejecuta normalmente
   npx expo start
   ```

3. **Verifica en los logs de la app:**
   - Deberías ver: `✅ Servidor encontrado en: https://mecanimovil-api.onrender.com/api`
   - No deberías ver errores de conexión

---

## 🔄 Flujo de Desarrollo

### Desarrollo Local

```bash
# 1. Inicia el servidor local
cd mecanimovil-backend
python manage.py runserver

# 2. La app detectará automáticamente el servidor local
# O usa ngrok si trabajas desde dispositivo físico
```

### Producción

```bash
# 1. Configura apiUrl en app.json
# 2. La app usará la URL de producción automáticamente
# 3. Deploy a Render (automático desde Git)
```

---

## 🚨 Troubleshooting

### Problema: La app no se conecta a producción

**Solución:**
1. Verifica que `apiUrl` esté configurado correctamente en `app.json`
2. Verifica que la API esté "Live" en Render
3. Verifica CORS en Render (debe estar en `True`)
4. Revisa los logs de la app para ver qué URL está intentando usar

### Problema: La app sigue usando localhost

**Solución:**
1. Verifica que `useNgrok` esté en `false`
2. Verifica que `apiUrl` esté configurado
3. Limpia la caché de Expo:
   ```bash
   npx expo start -c
   ```

### Problema: Error de CORS

**Solución:**
1. Ve a Render → `mecanimovil-api` → Environment
2. Verifica que `CORS_ALLOW_ALL_ORIGINS` esté en `True`
3. Reinicia el servicio después de cambiar variables

---

## 📝 Resumen de Configuración

| App | Archivo | Variable | Valor Producción |
|-----|---------|----------|------------------|
| **Usuarios** | `app.json` | `apiUrl` | `https://mecanimovil-api.onrender.com/api` |
| **Proveedores** | `.env` o `app.json` | `EXPO_PUBLIC_PRODUCTION_API_URL` | `https://mecanimovil-api.onrender.com` |

---

## ✅ Checklist de Verificación

- [ ] API responde en `https://mecanimovil-api.onrender.com/api/hello/`
- [ ] CORS está configurado (`CORS_ALLOW_ALL_ORIGINS = True`)
- [ ] `apiUrl` está configurado en `app.json` (app usuarios)
- [ ] `EXPO_PUBLIC_PRODUCTION_API_URL` está configurado (app proveedores)
- [ ] `useNgrok` está en `false` en producción
- [ ] La app se conecta correctamente (verificar logs)
- [ ] No hay errores de CORS en la app

---

## 🔗 URLs Importantes

- **API Base:** `https://mecanimovil-api.onrender.com`
- **API Endpoint:** `https://mecanimovil-api.onrender.com/api`
- **Health Check:** `https://mecanimovil-api.onrender.com/api/hello/`
