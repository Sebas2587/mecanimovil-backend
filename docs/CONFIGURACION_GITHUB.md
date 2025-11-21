# 📦 Configuración para GitHub - MecaniMóvil Backend

Este documento explica cómo está configurado el proyecto para GitHub, tanto para desarrollo local como para producción.

## ✅ Archivos Configurados para GitHub

### Archivos que SÍ se suben a GitHub

- ✅ `requirements.txt` - Dependencias del proyecto
- ✅ `manage.py` - Script de gestión de Django
- ✅ `mecanimovilapp/` - Código fuente completo
- ✅ `README_BACKEND.md` - Documentación principal
- ✅ `README_DESARROLLO.md` - Guía de desarrollo
- ✅ `CONFIGURACION_GITHUB.md` - Este archivo
- ✅ `.gitignore` - Archivos ignorados
- ✅ Scripts de desarrollo: `start_dev.sh`, `setup_dev.sh`
- ✅ Scripts de producción: `deploy_production.sh`

### Archivos que NO se suben a GitHub (en .gitignore)

- ❌ `venv/` - Entorno virtual
- ❌ `.env` - Variables de entorno (contiene credenciales)
- ❌ `*.pyc`, `__pycache__/` - Archivos compilados de Python
- ❌ `db.sqlite3` - Base de datos SQLite (si se usa)
- ❌ `*.log` - Archivos de log
- ❌ `media/` - Archivos subidos por usuarios
- ❌ `staticfiles/` - Archivos estáticos compilados
- ❌ `.env.local`, `.env.production` - Variables de entorno específicas

## 🚀 Desarrollo Local

### Pasos para Nuevos Desarrolladores

1. **Clonar el repositorio:**
   ```bash
   git clone <url-del-repositorio>
   cd mecanimovil-backend
   ```

2. **Configurar entorno de desarrollo:**
   ```bash
   chmod +x setup_dev.sh
   ./setup_dev.sh
   ```

3. **Crear archivo `.env`:**
   El script `setup_dev.sh` crea un `.env` de ejemplo. Configura las variables según tu entorno local.

4. **Iniciar servidor de desarrollo:**
   ```bash
   ./start_dev.sh
   ```

## 🔐 Gestión de Credenciales

### Desarrollo Local

Cada desarrollador debe crear su propio archivo `.env` local con:
- Credenciales de base de datos local
- Variables de entorno específicas de su máquina
- Credenciales de prueba de Mercado Pago (test)

### Producción

Las credenciales de producción deben:
- ⚠️ **NUNCA** subirse a GitHub
- Configurarse en el servidor de producción
- Usarse mediante variables de entorno del sistema
- O almacenarse en un gestor de secretos (AWS Secrets Manager, HashiCorp Vault, etc.)

## 📋 Estructura para GitHub

```
mecanimovil-backend/
├── .gitignore                    # ✅ Se sube
├── requirements.txt              # ✅ Se sube
├── manage.py                     # ✅ Se sube
├── setup_dev.sh                  # ✅ Se sube
├── start_dev.sh                  # ✅ Se sube
├── deploy_production.sh          # ✅ Se sube
├── README_BACKEND.md             # ✅ Se sube
├── README_DESARROLLO.md          # ✅ Se sube
├── CONFIGURACION_GITHUB.md       # ✅ Se sube (este archivo)
├── mecanimovilapp/               # ✅ Se sube (código fuente)
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   ├── wsgi.py
│   └── apps/
├── venv/                         # ❌ NO se sube (en .gitignore)
├── .env                          # ❌ NO se sube (en .gitignore)
├── db.sqlite3                    # ❌ NO se sube (en .gitignore)
├── media/                        # ❌ NO se sube (en .gitignore)
├── staticfiles/                  # ❌ NO se sube (en .gitignore)
└── *.log                         # ❌ NO se sube (en .gitignore)
```

## 🔄 Workflow de Git

### Para Desarrollo Local

```bash
# 1. Crear rama para nueva funcionalidad
git checkout -b feature/nueva-funcionalidad

# 2. Hacer cambios y commit
git add .
git commit -m "Descripción de los cambios"

# 3. Subir cambios
git push origin feature/nueva-funcionalidad

# 4. Crear Pull Request en GitHub
```

### Antes de Hacer Commit

⚠️ **IMPORTANTE:** Verifica que NO estés subiendo archivos sensibles:

```bash
# Verificar archivos que se van a subir
git status

# Verificar que .env NO esté en el staging
git diff --cached .env  # No debería mostrar nada

# Si accidentalmente agregaste .env, quitarlo:
git reset HEAD .env
```

## 🛠️ Scripts Incluidos

### `setup_dev.sh`
- Configura el entorno de desarrollo desde cero
- Crea entorno virtual
- Instala dependencias
- Crea archivo `.env` de ejemplo
- Aplica migraciones

### `start_dev.sh`
- Inicia el servidor de desarrollo con Daphne
- Verifica que el entorno virtual esté activo
- Aplica migraciones pendientes
- Inicia servidor en puerto 8000 (o el especificado)

### `deploy_production.sh`
- Script de deployment para producción
- Configura Redis, PostgreSQL, Nginx
- Configura supervisor para Daphne
- **NOTA:** Este script debe ejecutarse en el servidor de producción

## 🔍 Verificación

Antes de hacer push a GitHub, verifica:

1. ✅ No hay archivos sensibles en el staging (`git status`)
2. ✅ El `.gitignore` está configurado correctamente
3. ✅ Las dependencias están en `requirements.txt`
4. ✅ La documentación está actualizada
5. ✅ Los scripts tienen permisos de ejecución (`chmod +x`)

## 📝 Variables de Entorno Necesarias

Cada desarrollador debe configurar estas variables en su `.env` local:

### Obligatorias para Desarrollo
- `DEBUG=True`
- `SECRET_KEY` (puede usar la de desarrollo)
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `REDIS_URL` (si usas WebSockets)

### Opcionales para Desarrollo
- `MERCADOPAGO_ACCESS_TOKEN` (credenciales de prueba)
- `MERCADOPAGO_PUBLIC_KEY` (credenciales de prueba)
- `MERCADOPAGO_WEBHOOK_SECRET`

## 🚨 Seguridad

### ✅ Buenas Prácticas

- ✅ `.env` siempre en `.gitignore`
- ✅ `venv/` siempre en `.gitignore`
- ✅ Archivos de log en `.gitignore`
- ✅ Credenciales de producción separadas de desarrollo
- ✅ Documentación clara sobre qué archivos son sensibles

### ❌ Qué NO Hacer

- ❌ Subir archivos `.env` a GitHub
- ❌ Subir credenciales hardcodeadas en el código
- ❌ Subir el entorno virtual `venv/`
- ❌ Subir bases de datos locales
- ❌ Subir archivos de log con información sensible

## 📚 Documentación Relacionada

- [README_BACKEND.md](README_BACKEND.md) - Documentación principal del proyecto
- [README_DESARROLLO.md](README_DESARROLLO.md) - Guía completa de desarrollo local

---

**¿Preguntas?** Revisa la documentación o abre un issue en el repositorio.

