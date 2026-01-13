# 🔄 Flujo de Desarrollo Local → Producción (Render)

Guía completa para trabajar en local y desplegar a producción en Render.

---

## 📋 Resumen del Flujo

```
Desarrollo Local → Git Commit → Git Push → Render Deploy Automático → Verificación
```

---

## 🛠️ Paso 1: Configuración Inicial

### 1.1 Clonar/Actualizar Repositorio

```bash
# Si ya tienes el repo clonado
cd mecanimovil-backend
git pull origin main

# Si es la primera vez
git clone https://github.com/TU_USUARIO/mecanimovil-backend.git
cd mecanimovil-backend
```

### 1.2 Configurar Entorno Virtual

```bash
# Crear entorno virtual
python -m venv venv

# Activar entorno virtual
# En macOS/Linux:
source venv/bin/activate
# En Windows:
venv\Scripts\activate
```

### 1.3 Instalar Dependencias

```bash
pip install -r requirements.txt
```

### 1.4 Configurar Variables de Entorno Locales

Crea un archivo `.env` en la raíz del proyecto:

```bash
# .env (solo para desarrollo local)
DEBUG=True
SECRET_KEY=tu-secret-key-local-aqui
DATABASE_URL=postgresql://usuario:password@localhost:5432/mecanimovil_local
REDIS_URL=redis://localhost:6379/0
DJANGO_SETTINGS_MODULE=mecanimovilapp.settings
```

**⚠️ Importante:** El archivo `.env` está en `.gitignore` y NO se sube a Git.

---

## 💻 Paso 2: Desarrollo Local

### 2.1 Ejecutar Migraciones Locales

```bash
# Crear base de datos local (si no existe)
createdb mecanimovil_local  # PostgreSQL

# Ejecutar migraciones
python manage.py migrate
```

### 2.2 Crear Superusuario (si es necesario)

```bash
python manage.py createsuperuser
```

### 2.3 Ejecutar Servidor Local

```bash
# Servidor Django
python manage.py runserver

# En otra terminal, Celery Worker (opcional para desarrollo)
celery -A mecanimovilapp worker -l info

# En otra terminal, Celery Beat (opcional para desarrollo)
celery -A mecanimovilapp beat -l info
```

### 2.4 Probar Cambios Localmente

```bash
# Probar API
curl http://localhost:8000/api/hello/

# Probar con Django shell
python manage.py shell

# Ejecutar tests (si tienes)
python manage.py test
```

---

## 📝 Paso 3: Preparar Cambios para Deploy

### 3.1 Verificar Cambios

```bash
# Ver qué archivos cambiaron
git status

# Ver diferencias
git diff

# Verificar que no hay archivos sensibles
git status
# Asegúrate de que .env, *.pyc, __pycache__ no estén en los cambios
```

### 3.2 Crear Migraciones (si modificaste modelos)

```bash
# Crear migraciones
python manage.py makemigrations

# Verificar migraciones
python manage.py showmigrations

# Probar migraciones localmente
python manage.py migrate
```

### 3.3 Verificar que Todo Funciona

```bash
# Verificar configuración Django
python manage.py check

# Verificar configuración de producción
python manage.py check --deploy --settings=mecanimovilapp.settings_production
```

---

## 🚀 Paso 4: Deploy a Producción

### 4.1 Commit de Cambios

```bash
# Agregar cambios
git add .

# Commit con mensaje descriptivo
git commit -m "feat: Descripción de los cambios"

# Ejemplos de mensajes:
# "feat: Agregar endpoint de usuarios"
# "fix: Corregir error en autenticación"
# "refactor: Optimizar consultas de base de datos"
```

### 4.2 Push a GitHub

```bash
# Push a la rama main
git push origin main

# Render detectará automáticamente el push
```

### 4.3 Monitorear Deploy en Render

1. **Ve a Render Dashboard → Tu servicio (`mecanimovil-api`)**
2. **Verifica "Events":**
   - Deberías ver "Deploy started" inmediatamente
   - Luego "Build started"
   - Finalmente "Deploy succeeded"
3. **Verifica "Logs":**
   - Busca errores durante el build
   - Verifica que el servidor inició correctamente
   - Busca mensajes de error

---

## ✅ Paso 5: Verificar Deploy

### 5.1 Verificar API

```bash
# Health check
curl https://mecanimovil-api.onrender.com/api/hello/

# Deberías ver:
# {"message":"Hello from MecaniMovil API!"}
```

### 5.2 Verificar Servicios

1. **API:** Debe estar "Live" en Render
2. **Database:** Debe estar "Available"
3. **Redis:** Debe estar "Available"
4. **Celery Worker:** Debe estar "Live"
5. **Celery Beat:** Debe estar "Live"

### 5.3 Verificar Logs

1. **API Logs:**
   - Ve a `mecanimovil-api` → Logs
   - Busca errores o warnings
   - Verifica que hay requests entrantes

2. **Celery Worker Logs:**
   - Ve a `mecanimovil-celery-worker` → Logs
   - Verifica que el worker está activo
   - Busca tareas ejecutadas

3. **Celery Beat Logs:**
   - Ve a `mecanimovil-celery-beat` → Logs
   - Verifica que está programando tareas

### 5.4 Script de Verificación Automática

```bash
# Ejecutar script de verificación
cd mecanimovil-backend
./scripts/verificar_produccion_completo.sh
```

---

## 🔄 Flujo Completo (Ejemplo)

```bash
# 1. Desarrollo local
cd mecanimovil-backend
source venv/bin/activate
python manage.py runserver

# 2. Hacer cambios en el código
# ... editar archivos ...

# 3. Probar localmente
curl http://localhost:8000/api/hello/

# 4. Crear migraciones (si es necesario)
python manage.py makemigrations
python manage.py migrate

# 5. Verificar cambios
git status
git diff

# 6. Commit y push
git add .
git commit -m "feat: Nueva funcionalidad"
git push origin main

# 7. Monitorear deploy en Render Dashboard

# 8. Verificar producción
curl https://mecanimovil-api.onrender.com/api/hello/
./scripts/verificar_produccion_completo.sh
```

---

## 🚨 Troubleshooting

### Problema: Deploy falla en Render

**Solución:**
1. Revisa los logs del build en Render
2. Verifica que `requirements.txt` esté actualizado
3. Verifica que `build.sh` tenga permisos de ejecución
4. Verifica que no haya errores de sintaxis en el código

### Problema: Migraciones fallan en producción

**Solución:**
1. Verifica que las migraciones se crearon localmente
2. Prueba las migraciones localmente primero
3. Si hay conflictos, resuélvelos localmente antes de deployar

### Problema: Servicio no inicia después del deploy

**Solución:**
1. Revisa los logs del servicio
2. Verifica variables de entorno en Render
3. Verifica que el `startCommand` sea correcto
4. Verifica que las dependencias estén instaladas

### Problema: Cambios no se reflejan

**Solución:**
1. Verifica que el commit se hizo correctamente
2. Verifica que el push se completó
3. Verifica que Render detectó el cambio (ve a Events)
4. Espera a que el deploy termine (puede tardar 2-5 minutos)

---

## 📝 Checklist de Deploy

Antes de hacer deploy, verifica:

- [ ] Cambios probados localmente
- [ ] Migraciones creadas y probadas (si aplica)
- [ ] Tests pasan (si tienes)
- [ ] No hay archivos sensibles en el commit (.env, secrets)
- [ ] `requirements.txt` actualizado
- [ ] Código sin errores de sintaxis
- [ ] Mensaje de commit descriptivo

Después del deploy, verifica:

- [ ] Deploy completado en Render
- [ ] Servicio está "Live"
- [ ] API responde correctamente
- [ ] Logs no muestran errores
- [ ] Celery workers funcionando
- [ ] Apps móviles se conectan correctamente

---

## 🔗 Recursos

- [Guía de Acceso SSH/Shell](ACCESO_SSH_RENDER.md)
- [Guía de Verificación de Producción](VERIFICAR_PRODUCCION.md)
- [Guía de Configuración de Apps](CONFIGURAR_APPS_PRODUCCION.md)
- [Script de Verificación Completa](../scripts/verificar_produccion_completo.sh)
