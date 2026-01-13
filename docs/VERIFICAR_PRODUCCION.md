# ✅ Guía de Verificación de Producción - Render

Esta guía te ayuda a verificar que todos los servicios estén funcionando correctamente en producción.

---

## 📊 Paso 1: Verificar Estado de Servicios en Render

### 1.1 Acceder al Dashboard

1. Ve a [Render Dashboard](https://dashboard.render.com)
2. Inicia sesión

### 1.2 Verificar Estado de Cada Servicio

Revisa que todos los servicios estén en estado **"Live"** (verde):

| Servicio | Estado Esperado | Qué Hace |
|----------|----------------|----------|
| `mecanimovil-api` | 🟢 Live | API principal (Django + Daphne) |
| `mecanimovil-celery-worker` | 🟢 Live | Procesa tareas asíncronas |
| `mecanimovil-celery-beat` | 🟢 Live | Ejecuta tareas programadas |
| `mecanimovil-redis` | 🟢 Live | Cache y mensajería |
| `mecanimovil-db` | 🟢 Live | Base de datos PostgreSQL |

**Si algún servicio está en rojo (Failed):**
- Haz clic en el servicio
- Ve a "Logs" para ver el error
- Comparte el error para solucionarlo

---

## 🌐 Paso 2: Obtener la URL de tu API

### 2.1 Encontrar la URL

1. Ve a Render Dashboard → `mecanimovil-api`
2. En la parte superior verás la URL, algo como:
   ```
   https://mecanimovil-api.onrender.com
   ```
3. **Copia esa URL** - la necesitarás para conectar tu app

### 2.2 Probar la API desde el Navegador

Abre la URL en tu navegador. Deberías ver:
- Un error 404 (normal, significa que el servidor funciona)
- O una respuesta JSON si tienes un endpoint configurado

**Endpoint de prueba:**
```
https://mecanimovil-api.onrender.com/api/hello/
```

Si funciona, deberías ver una respuesta JSON.

---

## 📋 Paso 3: Verificar Logs de Cada Servicio

### 3.1 Logs del API (mecanimovil-api)

1. Ve a `mecanimovil-api` → **"Logs"**
2. Deberías ver:
   - ✅ `Starting server at tcp:port=...`
   - ✅ `Application startup complete`
   - ✅ Sin errores en rojo

**Busca errores:**
- ❌ `ERROR` o `Exception`
- ❌ `Connection refused`
- ❌ `ModuleNotFoundError`

### 3.2 Logs de Celery Worker

1. Ve a `mecanimovil-celery-worker` → **"Logs"**
2. Deberías ver:
   - ✅ `celery@... ready`
   - ✅ `[queues]` mostrando las colas configuradas
   - ✅ Sin errores

**Busca:**
- ✅ `celery@hostname ready`
- ✅ `[queues: default, heavy]`

### 3.3 Logs de Celery Beat

1. Ve a `mecanimovil-celery-beat` → **"Logs"**
2. Deberías ver:
   - ✅ `beat: Starting...`
   - ✅ `Scheduler: Sending due task...`
   - ✅ Sin errores

### 3.4 Logs de Redis

1. Ve a `mecanimovil-redis` → **"Logs"**
2. Deberías ver:
   - ✅ `Ready to accept connections`
   - ✅ Sin errores

---

## 🔍 Paso 4: Verificar Redis Funcionando

### 4.1 Desde los Logs

1. Ve a `mecanimovil-redis` → **"Logs"**
2. Busca mensajes como:
   - ✅ `Ready to accept connections`
   - ✅ `The server is now ready to accept connections`

### 4.2 Desde el API (si tienes un endpoint de prueba)

Puedes crear un endpoint simple para verificar Redis:

```python
# En algún view de prueba
from django.core.cache import cache

def test_redis(request):
    cache.set('test_key', 'test_value', 30)
    value = cache.get('test_key')
    return JsonResponse({'redis_working': value == 'test_value'})
```

### 4.3 Métricas en Render

1. Ve a `mecanimovil-redis` → **"Metrics"**
2. Deberías ver:
   - **Memory Usage** (debe estar por debajo del límite)
   - **Connections** (debe haber conexiones activas)

---

## ⚙️ Paso 5: Verificar Celery Funcionando

### 5.1 Verificar Worker

1. Ve a `mecanimovil-celery-worker` → **"Logs"**
2. Busca:
   - ✅ `celery@hostname ready`
   - ✅ `[queues: default, heavy]`
   - ✅ Sin errores de conexión a Redis o DB

### 5.2 Verificar Beat

1. Ve a `mecanimovil-celery-beat` → **"Logs"**
2. Busca:
   - ✅ `beat: Starting...`
   - ✅ `DatabaseScheduler: Schedule changed`
   - ✅ Sin errores

### 5.3 Probar una Tarea (Opcional)

Si tienes un endpoint que dispara una tarea de Celery, pruébalo y verifica en los logs del worker que se procese.

---

## 📱 Paso 6: Conectar tu App Expo

### 6.1 Obtener la URL de la API

La URL de tu API es:
```
https://mecanimovil-api.onrender.com
```
*(Reemplaza con tu URL real)*

### 6.2 Configurar en tu App Expo

En tu app React Native/Expo, actualiza la URL base:

**Archivo de configuración (ej: `config.js` o `constants.js`):**

```javascript
// config.js
export const API_URL = 'https://mecanimovil-api.onrender.com';

// O si tienes diferentes entornos:
export const API_URL = __DEV__ 
  ? 'http://localhost:8000'  // Desarrollo local
  : 'https://mecanimovil-api.onrender.com';  // Producción
```

### 6.3 Actualizar Todas las Peticiones

Asegúrate de que todas tus peticiones usen `API_URL`:

```javascript
import { API_URL } from './config';

// Ejemplo de petición
const response = await fetch(`${API_URL}/api/usuarios/login/`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ email, password }),
});
```

### 6.4 Probar desde Expo

1. Ejecuta tu app:
   ```bash
   npx expo start
   ```

2. Abre en tu dispositivo o emulador

3. Intenta hacer login o cualquier petición a la API

4. Verifica en los logs de Render (`mecanimovil-api` → Logs) que veas las peticiones llegando

---

## 🧪 Paso 7: Pruebas de Conectividad

### 7.1 Probar desde el Navegador

Abre la consola del navegador (F12) y ejecuta:

```javascript
// Probar endpoint básico
fetch('https://mecanimovil-api.onrender.com/api/hello/')
  .then(r => r.json())
  .then(data => console.log('✅ API funciona:', data))
  .catch(error => console.error('❌ Error:', error));

// Probar con CORS
fetch('https://mecanimovil-api.onrender.com/api/hello/', {
  method: 'GET',
  headers: {
    'Content-Type': 'application/json',
  },
})
  .then(r => r.json())
  .then(data => console.log('✅ CORS funciona:', data))
  .catch(error => console.error('❌ Error CORS:', error));
```

### 7.2 Probar desde Terminal (curl)

```bash
# Probar endpoint básico
curl https://mecanimovil-api.onrender.com/api/hello/

# Probar con headers
curl -H "Content-Type: application/json" \
     https://mecanimovil-api.onrender.com/api/hello/
```

### 7.3 Verificar en los Logs

Después de hacer las peticiones:
1. Ve a `mecanimovil-api` → **"Logs"**
2. Deberías ver las peticiones llegando:
   - ✅ `GET /api/hello/ HTTP/1.1" 200`
   - ✅ Sin errores 500 o 404

---

## 🔐 Paso 8: Verificar Autenticación

### 8.1 Probar Login

Desde tu app Expo o usando curl:

```bash
curl -X POST https://mecanimovil-api.onrender.com/api/usuarios/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "tu-email@ejemplo.com", "password": "tu-password"}'
```

**Respuesta esperada:**
- ✅ `200 OK` con token JWT
- ✅ O `401 Unauthorized` si las credenciales son incorrectas

### 8.2 Verificar en Logs

1. Ve a `mecanimovil-api` → **"Logs"**
2. Deberías ver:
   - ✅ `POST /api/usuarios/login/`
   - ✅ Sin errores de autenticación

---

## 📊 Paso 9: Verificar Base de Datos

### 9.1 Desde Render

1. Ve a `mecanimovil-db` → **"Info"**
2. Verifica:
   - ✅ Estado: "Available"
   - ✅ Host y puerto configurados
   - ✅ Usuario y base de datos correctos

### 9.2 Desde los Logs del API

1. Ve a `mecanimovil-api` → **"Logs"**
2. Busca errores de conexión a la base de datos:
   - ❌ `OperationalError`
   - ❌ `could not connect to server`
   - ❌ `database does not exist`

Si no hay estos errores, la conexión está funcionando.

### 9.3 Conectar con Cliente SQL (Opcional)

Puedes usar **pgAdmin** o **DBeaver**:

**Información de conexión:**
- **Host:** Lo verás en `mecanimovil-db` → Info
- **Port:** 5432 (generalmente)
- **Database:** mecanimovil
- **User:** mecanimovil
- **Password:** Haz clic en "Show" en Render para verla

---

## 🎯 Paso 10: Checklist Completo

### Servicios:
- [ ] Todos los servicios están "Live" (verde)
- [ ] No hay servicios en "Failed" (rojo)
- [ ] Todos los servicios tienen logs sin errores críticos

### API:
- [ ] La URL de la API funciona en el navegador
- [ ] El endpoint `/api/hello/` responde correctamente
- [ ] Los logs muestran peticiones llegando
- [ ] No hay errores 500 en los logs

### Redis:
- [ ] Redis está "Live"
- [ ] Los logs muestran "Ready to accept connections"
- [ ] No hay errores de conexión en los logs del API

### Celery:
- [ ] Worker está "Live" y muestra "ready"
- [ ] Beat está "Live" y muestra "Starting"
- [ ] No hay errores de conexión a Redis o DB

### Base de Datos:
- [ ] La base de datos está "Available"
- [ ] No hay errores de conexión en los logs
- [ ] Las migraciones se ejecutaron correctamente

### App Móvil:
- [ ] La URL de la API está configurada correctamente
- [ ] Puedo hacer peticiones desde la app
- [ ] El login funciona (si lo probaste)
- [ ] No hay errores de CORS
- [ ] No hay errores de conexión de red

---

## 🚨 Solución de Problemas Comunes

### Problema: "Network request failed" en Expo

**Soluciones:**
1. Verifica que la URL use `https://` (no `http://`)
2. Verifica que el servicio esté "Live" en Render
3. Verifica que no haya errores en los logs del API
4. Prueba desde el navegador primero para confirmar que la API funciona

### Problema: Error 500 en la API

**Soluciones:**
1. Ve a los logs de `mecanimovil-api`
2. Busca el traceback del error
3. Verifica que todas las variables de entorno estén configuradas
4. Verifica que la base de datos esté accesible

### Problema: Celery no procesa tareas

**Soluciones:**
1. Verifica que `mecanimovil-celery-worker` esté "Live"
2. Verifica que Redis esté funcionando
3. Revisa los logs del worker para ver errores
4. Verifica que `REDIS_URL` esté configurado correctamente

### Problema: Error de CORS

**Soluciones:**
1. Verifica que `CORS_ALLOW_ALL_ORIGINS = True` esté configurado
2. Verifica que el código esté actualizado en Render
3. Limpia la caché de tu app Expo
4. Reinicia el servicio `mecanimovil-api` en Render

---

## 📱 Probar desde Expo - Paso a Paso

### 1. Actualizar Configuración

En tu proyecto Expo, actualiza la URL de la API:

```javascript
// config/api.js o similar
const API_BASE_URL = 'https://mecanimovil-api.onrender.com';

export default API_BASE_URL;
```

### 2. Reiniciar Expo

```bash
# Detén Expo si está corriendo (Ctrl+C)
# Luego reinicia
npx expo start --clear
```

### 3. Probar Conexión

En tu app, agrega un botón de prueba temporal:

```javascript
const testConnection = async () => {
  try {
    const response = await fetch('https://mecanimovil-api.onrender.com/api/hello/');
    const data = await response.json();
    console.log('✅ Conexión exitosa:', data);
    Alert.alert('Éxito', 'Conexión a la API funcionando!');
  } catch (error) {
    console.error('❌ Error de conexión:', error);
    Alert.alert('Error', `No se pudo conectar: ${error.message}`);
  }
};
```

### 4. Verificar en Render

Mientras pruebas desde Expo:
1. Ve a `mecanimovil-api` → **"Logs"**
2. Deberías ver las peticiones llegando en tiempo real
3. Si no ves peticiones, hay un problema de conectividad

---

## 🎉 ¡Todo Listo!

Si todos los checkboxes están marcados, tu aplicación está funcionando correctamente en producción.

**Próximos pasos:**
- Monitorear los logs regularmente
- Configurar alertas en Render (opcional)
- Optimizar recursos según el uso
- Configurar dominio personalizado (opcional)

---

## 📞 ¿Necesitas Ayuda?

Si algo no funciona:
1. Revisa los logs del servicio que falla
2. Verifica las variables de entorno
3. Asegúrate de que el código esté actualizado
4. Comparte los logs del error para diagnóstico
