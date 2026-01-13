# 🔧 Crear Servicios de Celery Manualmente en Render

Si el Blueprint falla al sincronizar, puedes crear los servicios de Celery manualmente.

---

## 📋 Información Necesaria Antes de Crear

Necesitas estos valores de tus servicios existentes:

1. **SECRET_KEY del API:**
   - Ve a `mecanimovil-api` → Environment
   - Copia el valor de `SECRET_KEY`

2. **DATABASE_URL:**
   - Ve a `mecanimovil-db` → Info
   - Copia la "Internal Database URL" o "Connection String"

3. **REDIS_URL:**
   - Ve a `mecanimovil-redis` → Info
   - Copia la "Internal Redis URL" o "Connection String"

---

## 🛠️ Crear Celery Worker

### Paso 1: Crear el Worker

1. Ve a Render Dashboard → **"New"** → **"Background Worker"**
2. Conecta tu repositorio de GitHub (si no está conectado)
3. Selecciona el repositorio: `mecanimovil-backend`
4. Configura:

**Configuración Básica:**
- **Name:** `mecanimovil-celery-worker`
- **Environment:** `Python 3`
- **Region:** `Oregon` (igual que tus otros servicios)
- **Branch:** `main` (o la rama que uses)
- **Root Directory:** (déjalo vacío o `/`)

**Build & Deploy:**
- **Build Command:** `./build_worker.sh`
- **Start Command:** `celery -A mecanimovilapp worker -l info -Q default,heavy --concurrency=2`

**Plan:**
- Selecciona `Free` (o el plan que prefieras)

### Paso 2: Configurar Variables de Entorno

En la sección "Environment Variables", agrega:

```
PYTHON_VERSION = 3.11.7
DJANGO_SETTINGS_MODULE = mecanimovilapp.settings_production
DEBUG = False
SECRET_KEY = [pega el SECRET_KEY del API]
DATABASE_URL = [pega el DATABASE_URL de la base de datos]
REDIS_URL = [pega el REDIS_URL de Redis]
```

**Cómo obtener los valores:**

**SECRET_KEY:**
1. Ve a `mecanimovil-api` → Environment
2. Busca `SECRET_KEY`
3. Haz clic en "Show" y copia el valor

**DATABASE_URL:**
1. Ve a `mecanimovil-db` → Info
2. Busca "Internal Database URL" o "Connection String"
3. Copia el valor completo

**REDIS_URL:**
1. Ve a `mecanimovil-redis` → Info
2. Busca "Internal Redis URL" o "Connection String"
3. Copia el valor completo

### Paso 3: Crear el Servicio

1. Haz clic en **"Create Background Worker"**
2. Espera a que se despliegue (puede tardar 3-5 minutos)

---

## ⏰ Crear Celery Beat

Repite los mismos pasos pero con:

**Configuración:**
- **Name:** `mecanimovil-celery-beat`
- **Start Command:** `celery -A mecanimovilapp beat -l info`

**Variables de Entorno:** (iguales que el worker)

---

## ✅ Verificar que Funcionan

### Celery Worker:

1. Ve a `mecanimovil-celery-worker` → **"Logs"**
2. Deberías ver:
   ```
   celery@hostname ready
   [queues: default, heavy]
   ```

### Celery Beat:

1. Ve a `mecanimovil-celery-beat` → **"Logs"**
2. Deberías ver:
   ```
   beat: Starting...
   DatabaseScheduler: Schedule changed
   ```

---

## 🔄 Alternativa: Usar el Mismo SECRET_KEY

Si prefieres que todos los servicios compartan el mismo SECRET_KEY automáticamente:

1. Ve a `mecanimovil-api` → Environment
2. Copia el valor de `SECRET_KEY`
3. En cada worker, configura `SECRET_KEY` con ese mismo valor

Esto asegura que todos los servicios usen el mismo secret.

---

## 🚨 Si Hay Errores

### Error: "No module named 'celery'"
**Solución:** Verifica que `build_worker.sh` esté en el repositorio y tenga permisos de ejecución

### Error: "Could not connect to Redis"
**Solución:** 
1. Verifica que `REDIS_URL` sea correcta
2. Verifica que `mecanimovil-redis` esté "Live"

### Error: "Could not connect to database"
**Solución:**
1. Verifica que `DATABASE_URL` sea correcta
2. Verifica que `mecanimovil-db` esté "Available"

### Error: "SECRET_KEY is required"
**Solución:**
1. Asegúrate de haber configurado `SECRET_KEY` en las variables de entorno
2. Usa el mismo valor que tiene `mecanimovil-api`

---

## 📝 Resumen de Comandos

| Servicio | Build Command | Start Command |
|----------|---------------|---------------|
| **Celery Worker** | `./build_worker.sh` | `celery -A mecanimovilapp worker -l info -Q default,heavy --concurrency=2` |
| **Celery Beat** | `./build_worker.sh` | `celery -A mecanimovilapp beat -l info` |

---

## ✅ Checklist

- [ ] Tengo el SECRET_KEY del API
- [ ] Tengo el DATABASE_URL de la base de datos
- [ ] Tengo el REDIS_URL de Redis
- [ ] Creé `mecanimovil-celery-worker` con todas las variables
- [ ] Creé `mecanimovil-celery-beat` con todas las variables
- [ ] Ambos servicios están "Live"
- [ ] Los logs muestran que están funcionando
