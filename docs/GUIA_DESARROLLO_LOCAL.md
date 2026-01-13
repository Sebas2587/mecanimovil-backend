# 🛠️ Guía Completa: Desarrollo Local → Producción

Guía paso a paso para trabajar en desarrollo local y desplegar cambios a producción de forma segura.

---

## 📋 Tabla de Contenidos

1. [Configuración Inicial](#1-configuración-inicial)
2. [Flujo de Trabajo Diario](#2-flujo-de-trabajo-diario)
3. [Hacer Cambios](#3-hacer-cambios)
4. [Probar Localmente](#4-probar-localmente)
5. [Subir a Producción](#5-subir-a-producción)
6. [Verificar en Producción](#6-verificar-en-producción)
7. [Mejores Prácticas](#7-mejores-prácticas)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Configuración Inicial

### 1.1 Clonar el Repositorio

```bash
# Si es la primera vez
git clone https://github.com/Sebas2587/mecanimovil-backend.git
cd mecanimovil-backend

# Si ya lo tienes clonado, actualiza
cd mecanimovil-backend
git pull origin main
```

### 1.2 Crear Entorno Virtual

```bash
# Crear entorno virtual
python -m venv venv

# Activar entorno virtual
# En macOS/Linux:
source venv/bin/activate

# En Windows:
venv\Scripts\activate

# Verificar que está activado (deberías ver (venv) en el prompt)
```

### 1.3 Instalar Dependencias

```bash
# Instalar todas las dependencias
pip install -r requirements.txt

# Verificar instalación
pip list
```

### 1.4 Configurar Variables de Entorno Locales

Crea un archivo `.env` en la raíz del proyecto:

```bash
# Copiar plantilla (si existe)
cp .env.example .env

# O crear manualmente
touch .env
```

Edita `.env` con tus valores locales:

```bash
# .env (solo para desarrollo local - NO se sube a Git)
DEBUG=True
SECRET_KEY=tu-secret-key-local-aqui-puede-ser-cualquier-cosa
DATABASE_URL=postgresql://usuario:password@localhost:5432/mecanimovil_local
REDIS_URL=redis://localhost:6379/0
DJANGO_SETTINGS_MODULE=mecanimovilapp.settings

# Email (opcional para desarrollo)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

**⚠️ IMPORTANTE:** El archivo `.env` está en `.gitignore` y NO se sube a Git.

### 1.5 Configurar Base de Datos Local

```bash
# Crear base de datos local (PostgreSQL)
createdb mecanimovil_local

# O desde psql:
psql -U postgres
CREATE DATABASE mecanimovil_local;
\q

# Ejecutar migraciones
python manage.py migrate

# Crear superusuario local (opcional)
python manage.py createsuperuser
```

### 1.6 Verificar que Todo Funciona

```bash
# Ejecutar servidor local
python manage.py runserver

# En otra terminal, probar
curl http://localhost:8000/api/hello/

# Deberías ver:
# {"message":"¡Hola desde el backend de MecaniMovil!"}
```

---

## 2. Flujo de Trabajo Diario

### 2.1 Iniciar Sesión de Desarrollo

```bash
# 1. Ir al directorio del proyecto
cd mecanimovil-backend

# 2. Activar entorno virtual
source venv/bin/activate  # macOS/Linux
# o
venv\Scripts\activate  # Windows

# 3. Actualizar código (si trabajas en equipo)
git pull origin main

# 4. Verificar que todo está actualizado
git status
```

### 2.2 Trabajar en una Rama (Recomendado)

```bash
# Crear una nueva rama para tu feature
git checkout -b feature/nombre-de-tu-feature

# Ejemplo:
git checkout -b feature/agregar-endpoint-usuarios
```

**¿Por qué usar ramas?**
- Permite trabajar sin afectar `main`
- Fácil de revertir si algo sale mal
- Permite revisar cambios antes de mergear

---

## 3. Hacer Cambios

### 3.1 Estructura del Proyecto

```
mecanimovil-backend/
├── mecanimovilapp/
│   ├── apps/
│   │   ├── usuarios/      # App de usuarios
│   │   ├── servicios/     # App de servicios
│   │   ├── vehiculos/     # App de vehículos
│   │   └── ...
│   ├── settings.py        # Settings de desarrollo
│   └── settings_production.py  # Settings de producción
├── requirements.txt        # Dependencias Python
├── render.yaml            # Configuración Render
└── .env                   # Variables locales (NO se sube)
```

### 3.2 Hacer Cambios en el Código

1. **Edita los archivos necesarios** en tu editor (VS Code, PyCharm, etc.)
2. **Guarda los cambios**
3. **Verifica que no hay errores de sintaxis**

### 3.3 Si Modificas Modelos (Base de Datos)

```bash
# 1. Crear migraciones
python manage.py makemigrations

# 2. Ver qué migraciones se crearon
python manage.py showmigrations

# 3. Aplicar migraciones localmente
python manage.py migrate

# 4. Verificar que funcionan
python manage.py runserver
```

**⚠️ IMPORTANTE:** Siempre prueba las migraciones localmente antes de subirlas.

---

## 4. Probar Localmente

### 4.1 Ejecutar Servidor Local

```bash
# Activar entorno virtual
source venv/bin/activate

# Ejecutar servidor
python manage.py runserver

# El servidor estará en: http://localhost:8000
```

### 4.2 Probar Endpoints

```bash
# En otra terminal, probar endpoints
curl http://localhost:8000/api/hello/
curl http://localhost:8000/api/usuarios/
```

### 4.3 Probar con Django Shell

```bash
python manage.py shell

# En el shell:
from mecanimovilapp.apps.usuarios.models import Usuario
Usuario.objects.count()
```

### 4.4 Verificar Configuración

```bash
# Verificar que no hay errores
python manage.py check

# Verificar configuración de producción (sin aplicar)
python manage.py check --deploy --settings=mecanimovilapp.settings_production
```

---

## 5. Subir a Producción

### 5.1 Verificar Cambios Antes de Subir

```bash
# Ver qué archivos cambiaron
git status

# Ver diferencias
git diff

# Verificar que NO hay archivos sensibles
# Asegúrate de que .env, *.pyc, __pycache__ NO estén en los cambios
```

### 5.2 Agregar Cambios

```bash
# Agregar archivos específicos (recomendado)
git add archivo1.py archivo2.py

# O agregar todos los cambios (cuidado)
git add .

# Verificar qué se agregó
git status
```

### 5.3 Commit con Mensaje Descriptivo

```bash
# Commit con mensaje descriptivo
git commit -m "feat: Agregar endpoint de usuarios"

# Ejemplos de mensajes:
# "feat: Agregar endpoint de usuarios"
# "fix: Corregir error en autenticación"
# "refactor: Optimizar consultas de base de datos"
# "docs: Actualizar documentación"
```

**Formato de mensajes:**
- `feat:` Nueva funcionalidad
- `fix:` Corrección de bug
- `refactor:` Refactorización de código
- `docs:` Cambios en documentación
- `test:` Agregar o modificar tests
- `chore:` Tareas de mantenimiento

### 5.4 Push a GitHub

```bash
# Si trabajaste en una rama
git push origin feature/nombre-de-tu-feature

# Luego hacer merge en GitHub (Pull Request)
# O mergear localmente y push a main:
git checkout main
git merge feature/nombre-de-tu-feature
git push origin main

# Si trabajaste directamente en main
git push origin main
```

**⚠️ IMPORTANTE:** Render detecta automáticamente el push y inicia un deploy.

---

## 6. Verificar en Producción

### 6.1 Monitorear Deploy en Render

1. **Ve a Render Dashboard → `mecanimovil-api`**
2. **Verifica "Events":**
   - Deberías ver "Deploy started" inmediatamente
   - Luego "Build started"
   - Finalmente "Deploy succeeded"
3. **Verifica "Logs":**
   - Busca errores durante el build
   - Verifica que el servidor inició correctamente

### 6.2 Probar API en Producción

```bash
# Health check
curl https://mecanimovil-api.onrender.com/api/hello/

# Probar tu nuevo endpoint (si agregaste uno)
curl https://mecanimovil-api.onrender.com/api/tu-endpoint/
```

### 6.3 Verificar Logs

1. **Ve a Render Dashboard → `mecanimovil-api` → Logs**
2. **Busca errores** (líneas rojas o con "ERROR")
3. **Verifica que no hay errores críticos**

### 6.4 Si Hay Errores

Ver sección [Troubleshooting](#8-troubleshooting) más abajo.

---

## 7. Mejores Prácticas

### 7.1 Antes de Hacer Commit

✅ **Siempre:**
- Probar cambios localmente
- Verificar que no hay errores de sintaxis
- Verificar que las migraciones funcionan (si aplica)
- Revisar qué archivos se van a subir (`git status`)
- Asegurarse de que no hay archivos sensibles (.env, secrets)

❌ **Nunca:**
- Subir archivos `.env` o con secrets
- Subir archivos `*.pyc` o `__pycache__`
- Hacer commit sin probar primero
- Subir cambios que rompen la aplicación

### 7.2 Trabajar con Ramas

```bash
# Crear rama para feature
git checkout -b feature/nueva-funcionalidad

# Trabajar en la rama
# ... hacer cambios ...

# Commit en la rama
git add .
git commit -m "feat: Nueva funcionalidad"

# Push la rama
git push origin feature/nueva-funcionalidad

# Crear Pull Request en GitHub (recomendado)
# O mergear localmente:
git checkout main
git merge feature/nueva-funcionalidad
git push origin main
```

### 7.3 Manejo de Migraciones

```bash
# 1. Crear migraciones localmente
python manage.py makemigrations

# 2. Probar migraciones localmente
python manage.py migrate

# 3. Verificar que funcionan
python manage.py runserver

# 4. Commit y push
git add */migrations/
git commit -m "feat: Agregar migraciones para modelo X"
git push origin main

# 5. Render aplicará las migraciones automáticamente en build.sh
```

### 7.4 Variables de Entorno

**Local (.env):**
```bash
# .env (NO se sube a Git)
DEBUG=True
SECRET_KEY=local-secret-key
DATABASE_URL=postgresql://localhost/mecanimovil_local
```

**Producción (Render Dashboard):**
- Configurar en Render Dashboard → Environment
- NO poner en el código
- NO poner en Git

### 7.5 Archivos que NO se Suben

El `.gitignore` ya está configurado para NO subir:
- `.env` (variables de entorno)
- `*.pyc` (bytecode Python)
- `__pycache__/` (caché Python)
- `venv/` (entorno virtual)
- `media/` (archivos subidos)
- `db.sqlite3` (base de datos local)

---

## 8. Troubleshooting

### Problema: "No puedo conectar a la base de datos local"

**Solución:**
```bash
# Verificar que PostgreSQL está corriendo
pg_isready

# Verificar que la base de datos existe
psql -l | grep mecanimovil

# Si no existe, crearla
createdb mecanimovil_local

# Verificar DATABASE_URL en .env
cat .env | grep DATABASE_URL
```

### Problema: "Error al hacer migrate"

**Solución:**
```bash
# Ver migraciones pendientes
python manage.py showmigrations

# Aplicar migraciones
python manage.py migrate

# Si hay conflictos, verificar el estado
python manage.py migrate --plan
```

### Problema: "Deploy falla en Render"

**Solución:**
1. Revisa los logs del build en Render
2. Verifica que `requirements.txt` esté actualizado
3. Verifica que `build.sh` tenga permisos de ejecución
4. Verifica que no hay errores de sintaxis

### Problema: "Cambios no se reflejan en producción"

**Solución:**
1. Verifica que el commit se hizo: `git log`
2. Verifica que el push se completó: `git status`
3. Verifica que Render detectó el cambio (ve a Events)
4. Espera a que el deploy termine (puede tardar 2-5 minutos)

### Problema: "Accidentalmente subí .env a Git"

**Solución:**
```bash
# 1. Eliminar del Git (pero mantener local)
git rm --cached .env

# 2. Commit
git commit -m "fix: Remover .env del repositorio"

# 3. Push
git push origin main

# 4. IMPORTANTE: Cambiar todas las variables en producción
# Ve a Render Dashboard y actualiza las variables de entorno
```

---

## 9. Checklist de Deploy

### Antes de Hacer Deploy

- [ ] Cambios probados localmente
- [ ] Migraciones creadas y probadas (si aplica)
- [ ] No hay errores de sintaxis
- [ ] No hay archivos sensibles en el commit
- [ ] `requirements.txt` actualizado (si agregaste dependencias)
- [ ] Mensaje de commit descriptivo

### Después del Deploy

- [ ] Deploy completado en Render
- [ ] Servicio está "Live"
- [ ] API responde correctamente
- [ ] Logs no muestran errores
- [ ] Migraciones aplicadas (si aplica)
- [ ] Funcionalidad nueva funciona en producción

---

## 10. Comandos Útiles

### Git

```bash
# Ver estado
git status

# Ver diferencias
git diff

# Ver historial
git log --oneline

# Deshacer cambios no commiteados
git checkout -- archivo.py

# Deshacer último commit (mantener cambios)
git reset --soft HEAD~1

# Ver ramas
git branch

# Cambiar de rama
git checkout nombre-rama
```

### Django

```bash
# Ejecutar servidor
python manage.py runserver

# Crear migraciones
python manage.py makemigrations

# Aplicar migraciones
python manage.py migrate

# Verificar configuración
python manage.py check

# Crear superusuario
python manage.py createsuperuser

# Django shell
python manage.py shell
```

---

## 11. Resumen del Flujo Completo

```bash
# 1. Configuración inicial (solo una vez)
git clone https://github.com/TU_USUARIO/mecanimovil-backend.git
cd mecanimovil-backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Configurar .env
python manage.py migrate

# 2. Trabajo diario
cd mecanimovil-backend
source venv/bin/activate
git pull origin main  # Si trabajas en equipo

# 3. Hacer cambios
# ... editar archivos ...

# 4. Probar localmente
python manage.py runserver
# Probar en otra terminal

# 5. Commit y push
git add .
git commit -m "feat: Descripción de cambios"
git push origin main

# 6. Verificar en Render Dashboard
# Render despliega automáticamente

# 7. Verificar producción
curl https://mecanimovil-api.onrender.com/api/hello/
```

---

## 📚 Recursos Adicionales

- [Guía de Flujo Desarrollo → Producción](FLUJO_DESARROLLO_PRODUCCION.md)
- [Guía de Acceso SSH/Shell](ACCESO_SSH_RENDER.md)
- [Guía de Verificación de Producción](VERIFICAR_PRODUCCION.md)

---

**¡Listo! Ahora puedes trabajar en desarrollo local y desplegar a producción de forma segura.** 🎉
