# 🔧 Crear Servicios de Celery en Render

Esta guía te ayuda a crear los servicios de Celery que faltan en Render.

---

## 🎯 Opción 1: Sincronizar Blueprint (Recomendado)

### Paso 1: Sincronizar el Blueprint

1. Ve a [Render Dashboard](https://dashboard.render.com)
2. Ve a **"Blueprints"** en el menú lateral
3. Busca tu Blueprint (probablemente llamado "mecanimovil" o similar)
4. Haz clic en el Blueprint
5. Haz clic en **"Sync"** o **"Manual Deploy"** → **"Sync Blueprint"**
6. Render detectará los servicios faltantes y los creará automáticamente

### Paso 2: Verificar

Después de sincronizar, deberías ver:
- ✅ `mecanimovil-celery-worker` (Background Worker)
- ✅ `mecanimovil-celery-beat` (Background Worker)

---

## 🛠️ Opción 2: Crear Servicios Manualmente

Si la sincronización no funciona, puedes crear los servicios manualmente:

### Crear Celery Worker

1. Ve a Render Dashboard → **"New"** → **"Background Worker"**
2. Configura:
   - **Name:** `mecanimovil-celery-worker`
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `celery -A mecanimovilapp worker -l info -Q default,heavy --concurrency=2`
   - **Plan:** `Free` (o el plan que prefieras)
   - **Region:** `Oregon` (o la región de tus otros servicios)

3. **Variables de Entorno:**
   - `PYTHON_VERSION` = `3.11.7`
   - `DJANGO_SETTINGS_MODULE` = `mecanimovilapp.settings_production`
   - `DEBUG` = `False`
   - `SECRET_KEY` = (usa el mismo del servicio `mecanimovil-api`)
   - `DATABASE_URL` = (conecta a `mecanimovil-db`)
   - `REDIS_URL` = (conecta a `mecanimovil-redis`)

4. Haz clic en **"Create Background Worker"**

### Crear Celery Beat

1. Ve a Render Dashboard → **"New"** → **"Background Worker"**
2. Configura:
   - **Name:** `mecanimovil-celery-beat`
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `celery -A mecanimovilapp beat -l info`
   - **Plan:** `Free` (o el plan que prefieras)
   - **Region:** `Oregon` (o la región de tus otros servicios)

3. **Variables de Entorno:**
   - `PYTHON_VERSION` = `3.11.7`
   - `DJANGO_SETTINGS_MODULE` = `mecanimovilapp.settings_production`
   - `DEBUG` = `False`
   - `SECRET_KEY` = (usa el mismo del servicio `mecanimovil-api`)
   - `DATABASE_URL` = (conecta a `mecanimovil-db`)
   - `REDIS_URL` = (conecta a `mecanimovil-redis`)

4. Haz clic en **"Create Background Worker"**

---

## ✅ Verificar que Funcionan

### Verificar Celery Worker

1. Ve a `mecanimovil-celery-worker` → **"Logs"**
2. Deberías ver:
   - ✅ `celery@hostname ready`
   - ✅ `[queues: default, heavy]`
   - ✅ Sin errores

### Verificar Celery Beat

1. Ve a `mecanimovil-celery-beat` → **"Logs"**
2. Deberías ver:
   - ✅ `beat: Starting...`
   - ✅ `DatabaseScheduler: Schedule changed`
   - ✅ Sin errores

---

## 🔍 Comandos de Celery en render.yaml

Los comandos están configurados así:

**Celery Worker:**
```bash
celery -A mecanimovilapp worker -l info -Q default,heavy --concurrency=2
```

**Celery Beat:**
```bash
celery -A mecanimovilapp beat -l info
```

Estos comandos son correctos y funcionarán en producción.

---

## ⚠️ Si Hay Errores

### Error: "No module named 'celery'"
**Solución:** Verifica que `requirements.txt` incluya `celery==5.3.4`

### Error: "Could not connect to Redis"
**Solución:** 
1. Verifica que `REDIS_URL` esté configurada correctamente
2. Verifica que `mecanimovil-redis` esté "Live"

### Error: "Could not connect to database"
**Solución:**
1. Verifica que `DATABASE_URL` esté configurada correctamente
2. Verifica que `mecanimovil-db` esté "Available"

---

## 📋 Checklist

- [ ] Blueprint sincronizado O servicios creados manualmente
- [ ] `mecanimovil-celery-worker` está "Live"
- [ ] `mecanimovil-celery-beat` está "Live"
- [ ] Los logs muestran que están funcionando
- [ ] No hay errores de conexión a Redis o DB
