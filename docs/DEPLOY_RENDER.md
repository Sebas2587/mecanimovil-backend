# 🚀 Guía de Deployment en Render - MecaniMovil Backend

Esta guía te ayudará a desplegar el backend de MecaniMovil en Render paso a paso.

## 📋 Requisitos Previos

1. Cuenta en [Render](https://render.com)
2. Repositorio de código en GitHub/GitLab
3. Credenciales de Mercado Pago (producción)
4. (Opcional) Cuenta de AWS para S3 si usarás almacenamiento de archivos

## 🏗️ Arquitectura del Deployment

El deployment en Render incluye:

| Servicio | Tipo | Descripción |
|----------|------|-------------|
| `mecanimovil-api` | Web Service | Django + Daphne (ASGI) con WebSockets |
| `mecanimovil-celery-worker` | Background Worker | Procesamiento de tareas asíncronas |
| `mecanimovil-celery-beat` | Background Worker | Tareas programadas |
| `mecanimovil-db` | PostgreSQL | Base de datos con PostGIS |
| `mecanimovil-redis` | Redis | Cache, Channels, Celery broker |

## 🚀 Método 1: Deploy con Blueprint (Recomendado)

### Paso 1: Preparar el repositorio

1. Asegúrate de que tu código esté en GitHub/GitLab
2. Verifica que los siguientes archivos existan:
   - `render.yaml` (Blueprint de infraestructura)
   - `build.sh` (Script de build)
   - `requirements.txt` (Dependencias)
   - `runtime.txt` (Versión de Python)

### Paso 2: Conectar con Render

1. Ve a [Render Dashboard](https://dashboard.render.com)
2. Click en **"New"** → **"Blueprint"**
3. Conecta tu repositorio de GitHub/GitLab
4. Selecciona el repositorio de `mecanimovil-backend`
5. Render detectará automáticamente el `render.yaml`

### Paso 3: Configurar Variables de Entorno

Después de crear el Blueprint, necesitas configurar las siguientes variables manualmente en el Dashboard de Render:

#### En `mecanimovil-api`:

```
MERCADOPAGO_ACCESS_TOKEN=APP_USR-tu-token-produccion
MERCADOPAGO_MODE=production
MERCADOPAGO_WEBHOOK_SECRET=tu-webhook-secret
MERCADOPAGO_PUBLIC_KEY_PROD=tu-public-key

CORS_ALLOWED_ORIGINS=https://tu-app-frontend.com

EMAIL_HOST_USER=tu-email@gmail.com
EMAIL_HOST_PASSWORD=tu-app-password

# Opcional: Para crear superusuario automáticamente
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@mecanimovil.com
DJANGO_SUPERUSER_PASSWORD=tu-password-seguro
```

### Paso 4: Habilitar PostGIS

Después de que la base de datos se cree:

1. Ve al servicio `mecanimovil-db` en Render
2. Click en "Shell"
3. Ejecuta:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
```

### Paso 5: Deploy

1. Render iniciará automáticamente el deploy
2. El script `build.sh` se ejecutará:
   - Instalará dependencias
   - Ejecutará migraciones
   - Recolectará archivos estáticos
   - Creará el superusuario (si configuraste las variables)

## 🔧 Método 2: Deploy Manual

### Paso 1: Crear la Base de Datos

1. Ve a Render Dashboard → **"New"** → **"PostgreSQL"**
2. Configura:
   - Name: `mecanimovil-db`
   - Database: `mecanimovil`
   - User: `mecanimovil`
   - Region: Elige la más cercana
3. Una vez creada, habilita PostGIS (ver Paso 4 del Método 1)

### Paso 2: Crear Redis

1. Ve a Render Dashboard → **"New"** → **"Redis"**
2. Configura:
   - Name: `mecanimovil-redis`
   - Region: La misma que la base de datos

### Paso 3: Crear el Web Service

1. Ve a Render Dashboard → **"New"** → **"Web Service"**
2. Conecta tu repositorio
3. Configura:
   - Name: `mecanimovil-api`
   - Runtime: Python
   - Build Command: `./build.sh`
   - Start Command: `daphne -b 0.0.0.0 -p $PORT mecanimovilapp.asgi:application`
   - Health Check Path: `/api/hello/`

4. Variables de entorno:
   - `DJANGO_SETTINGS_MODULE`: `mecanimovilapp.settings_production`
   - `DATABASE_URL`: (copia de la base de datos)
   - `REDIS_URL`: (copia de Redis)
   - ... (resto de variables)

### Paso 4: Crear Workers de Celery

#### Worker:
1. **"New"** → **"Background Worker"**
2. Configura:
   - Name: `mecanimovil-celery-worker`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `celery -A mecanimovilapp worker -l info -Q default,heavy --concurrency=2`

#### Beat:
1. **"New"** → **"Background Worker"**
2. Configura:
   - Name: `mecanimovil-celery-beat`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `celery -A mecanimovilapp beat -l info`

## 📝 Variables de Entorno Completas

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `SECRET_KEY` | Clave secreta de Django | (auto-generada) |
| `DEBUG` | Modo debug | `False` |
| `ALLOWED_HOSTS` | Hosts permitidos | `.onrender.com,.mecanimovil.com` |
| `DATABASE_URL` | URL de PostgreSQL | (auto desde Render) |
| `REDIS_URL` | URL de Redis | (auto desde Render) |
| `MERCADOPAGO_ACCESS_TOKEN` | Token de acceso MP | `APP_USR-...` |
| `MERCADOPAGO_MODE` | Modo de MP | `production` |
| `MERCADOPAGO_WEBHOOK_SECRET` | Secret de webhook | `...` |
| `CORS_ALLOWED_ORIGINS` | Orígenes permitidos | `https://app.com` |
| `EMAIL_HOST` | Servidor SMTP | `smtp.gmail.com` |
| `EMAIL_PORT` | Puerto SMTP | `587` |
| `EMAIL_HOST_USER` | Usuario email | `tu@email.com` |
| `EMAIL_HOST_PASSWORD` | Contraseña email | `app-password` |

## 🔍 Verificación del Deploy

### 1. Verificar el API

```bash
curl https://tu-app.onrender.com/api/hello/
```

Respuesta esperada:
```json
{"message": "¡Hola desde el backend de MecaniMovil!"}
```

### 2. Verificar el Admin

1. Ve a `https://tu-app.onrender.com/admin/`
2. Inicia sesión con las credenciales del superusuario

### 3. Verificar WebSockets

Usa una herramienta como [wscat](https://github.com/websockets/wscat):

```bash
wscat -c wss://tu-app.onrender.com/ws/solicitudes/
```

### 4. Verificar Celery

En los logs del worker de Celery, deberías ver:
```
celery@... ready.
```

## 🐛 Solución de Problemas

### Error: "relation does not exist"

Las migraciones no se ejecutaron correctamente. Ejecuta manualmente:

```bash
# En el Shell del servicio web de Render
python manage.py migrate
```

### Error: "PostGIS extension not found"

Habilita PostGIS en la base de datos:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

### Error: "Redis connection refused"

Verifica que `REDIS_URL` esté configurada correctamente y que Redis esté corriendo.

### WebSockets no conectan

1. Verifica que estés usando `wss://` (no `ws://`)
2. Verifica que `ALLOWED_HOSTS` incluya tu dominio
3. Revisa los logs de Daphne

### Archivos estáticos no cargan

```bash
# En el Shell del servicio
python manage.py collectstatic --noinput
```

## 📊 Monitoreo

### Logs

Ve a cada servicio en Render → "Logs" para ver los logs en tiempo real.

### Métricas

Render proporciona métricas básicas de CPU, memoria y requests en el Dashboard.

### Health Checks

El endpoint `/api/hello/` se usa como health check. Si falla, Render reiniciará el servicio automáticamente.

## 💰 Costos Estimados

| Servicio | Plan Starter | Plan Standard |
|----------|--------------|---------------|
| Web Service | $7/mes | $25/mes |
| Worker (x2) | $7/mes c/u | $25/mes c/u |
| PostgreSQL | $7/mes | $20/mes |
| Redis | $0 (25MB) | $10/mes |
| **Total** | ~$28/mes | ~$105/mes |

## 🔄 Actualizaciones

Para actualizar la aplicación:

1. Haz push a la rama principal de tu repositorio
2. Render detectará los cambios y hará deploy automáticamente
3. El deploy es zero-downtime (sin interrupción)

## 📱 Configurar el Frontend

Actualiza la URL del API en tu app de React Native:

```javascript
// config.js
export const API_URL = 'https://tu-app.onrender.com';
export const WS_URL = 'wss://tu-app.onrender.com';
```

## 🔐 Configurar Dominio Personalizado

1. Ve al servicio web en Render
2. Click en "Settings" → "Custom Domains"
3. Agrega tu dominio (ej: `api.mecanimovil.com`)
4. Configura los registros DNS según las instrucciones de Render
5. Actualiza `ALLOWED_HOSTS` para incluir tu dominio

---

## ✅ Checklist de Deploy

- [ ] Repositorio conectado a Render
- [ ] Base de datos PostgreSQL creada
- [ ] PostGIS habilitado
- [ ] Redis creado
- [ ] Web service configurado
- [ ] Workers de Celery configurados
- [ ] Variables de entorno configuradas
- [ ] Migraciones ejecutadas
- [ ] Superusuario creado
- [ ] Health check funcionando
- [ ] WebSockets funcionando
- [ ] Frontend actualizado con nueva URL

---

¿Necesitas ayuda? Revisa los logs en el Dashboard de Render o contacta al equipo de desarrollo.
