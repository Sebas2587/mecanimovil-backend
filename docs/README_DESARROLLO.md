# 🚀 Guía de Desarrollo Local - MecaniMóvil Backend

Esta guía explica cómo configurar y ejecutar el backend de MecaniMóvil en tu entorno de desarrollo local.

## 📋 Requisitos Previos

Antes de comenzar, asegúrate de tener instalado:

- **Python 3.8+** (recomendado Python 3.10+)
- **PostgreSQL 12+** con PostGIS
- **Redis** (para WebSockets)
- **Git**

### Instalación en macOS

```bash
# Instalar PostgreSQL con PostGIS
brew install postgresql@14 postgis

# Instalar Redis
brew install redis

# Iniciar servicios
brew services start postgresql@14
brew services start redis
```

### Instalación en Linux (Ubuntu/Debian)

```bash
# Instalar PostgreSQL con PostGIS
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib postgis postgresql-postgis

# Instalar Redis
sudo apt-get install redis-server

# Iniciar servicios
sudo systemctl start postgresql
sudo systemctl start redis-server
```

## 🔧 Configuración Inicial

### 1. Clonar el Repositorio

```bash
git clone <url-del-repositorio>
cd mecanimovil-backend
```

### 2. Configuración Automática (Recomendado)

Usa el script de configuración automática:

```bash
chmod +x setup_dev.sh
./setup_dev.sh
```

Este script:
- ✅ Crea el entorno virtual
- ✅ Instala todas las dependencias
- ✅ Crea el archivo `.env` de ejemplo
- ✅ Aplica las migraciones
- ✅ Te permite crear un superusuario

### 3. Configuración Manual

Si prefieres configurar manualmente:

#### 3.1. Crear Entorno Virtual

```bash
python3 -m venv venv
source venv/bin/activate  # En macOS/Linux
# o
venv\Scripts\activate  # En Windows
```

#### 3.2. Instalar Dependencias

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### 3.3. Configurar Base de Datos

Crea una base de datos PostgreSQL:

```bash
# Conectar a PostgreSQL
psql postgres

# Crear base de datos
CREATE DATABASE mecanimovil;

# Salir
\q
```

#### 3.4. Configurar Variables de Entorno

Crea un archivo `.env` en la raíz del proyecto:

```env
# Django Settings
DEBUG=True
SECRET_KEY=django-insecure-k#t34sc+!o_g&y#d^f-jxfh%7u*6ya!rco%v8!c6(0ot8*6u@^
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

# Database (PostgreSQL)
DB_NAME=mecanimovil
DB_USER=tu_usuario_postgres
DB_PASSWORD=tu_contraseña
DB_HOST=localhost
DB_PORT=5432

# Redis (para WebSockets)
REDIS_URL=redis://localhost:6379/0

# Mercado Pago (credenciales de prueba para desarrollo)
MERCADOPAGO_ACCESS_TOKEN=TU_ACCESS_TOKEN_AQUI
MERCADOPAGO_PUBLIC_KEY=TU_PUBLIC_KEY_AQUI
MERCADOPAGO_WEBHOOK_SECRET=a7934fae72aca801d2bd08aeaa79b0d650c7900c0def8aa559583934d9de44ee
```

#### 3.5. Aplicar Migraciones

```bash
python manage.py migrate
```

#### 3.6. Crear Superusuario (Opcional)

```bash
python manage.py createsuperuser
```

## 🚀 Ejecutar Servidor de Desarrollo

### Método 1: Script Automático (Recomendado)

```bash
# Asegúrate de estar en el directorio mecanimovil-backend
chmod +x start_dev.sh
./start_dev.sh
```

O con un puerto específico:

```bash
./start_dev.sh 8080
```

### Método 2: Comando Directo

```bash
# Activar entorno virtual
source venv/bin/activate

# Iniciar con Daphne
daphne -b 0.0.0.0 -p 8000 mecanimovilapp.asgi:application
```

### Método 3: Usando Django Runserver (Solo para pruebas básicas)

⚠️ **Nota:** `runserver` no soporta WebSockets. Usa Daphne para desarrollo completo.

```bash
python manage.py runserver 0.0.0.0:8000
```

## 📝 Comandos Útiles

### Gestión de Base de Datos

```bash
# Crear migraciones
python manage.py makemigrations

# Aplicar migraciones
python manage.py migrate

# Ver estado de migraciones
python manage.py showmigrations

# Revertir última migración
python manage.py migrate app_name zero
```

### Gestión de Usuarios

```bash
# Crear superusuario
python manage.py createsuperuser

# Listar usuarios
python manage.py shell
>>> from mecanimovilapp.apps.usuarios.models import Usuario
>>> Usuario.objects.all()
```

### Shell de Django

```bash
python manage.py shell
```

### Verificar Configuración

```bash
# Verificar configuración de Django
python manage.py check

# Verificar configuración de canales (WebSockets)
python manage.py check --deploy
```

## 🔍 Verificación

Una vez que el servidor esté corriendo, verifica:

1. **API Base:** http://localhost:8000/api/
2. **Admin Panel:** http://localhost:8000/admin/
3. **API Docs:** http://localhost:8000/api/docs/ (si está configurado)

## ⚠️ Troubleshooting

### Puerto en Uso

Si el puerto 8000 está en uso:

```bash
# Encontrar proceso usando el puerto
lsof -i :8000

# Matar proceso
kill -9 <PID>

# O usar otro puerto
./start_dev.sh 8080
```

### Redis No Está Corriendo

```bash
# Verificar estado
redis-cli ping

# Si no responde "PONG", iniciar Redis
brew services start redis  # macOS
# o
sudo systemctl start redis-server  # Linux
```

### Error de Conexión a PostgreSQL

1. Verifica que PostgreSQL esté corriendo:
   ```bash
   brew services list  # macOS
   # o
   sudo systemctl status postgresql  # Linux
   ```

2. Verifica las credenciales en `.env`

3. Verifica que la base de datos exista:
   ```bash
   psql -l | grep mecanimovil
   ```

### Error de Migraciones Pendientes

```bash
python manage.py migrate
```

Si hay errores, verifica:
- Que la base de datos exista
- Que tengas permisos suficientes
- Que PostGIS esté instalado correctamente

## 🔐 Seguridad en Desarrollo

- ⚠️ **NUNCA** subas el archivo `.env` a Git
- ⚠️ **NUNCA** uses credenciales de producción en desarrollo
- ⚠️ **Siempre** usa `DEBUG=False` en producción
- ✅ El archivo `.gitignore` ya está configurado para ignorar archivos sensibles

## 📦 Dependencias Principales

- **Django 4.2.7** - Framework web
- **Django REST Framework** - API REST
- **Django Channels** - WebSockets
- **Daphne 4.0.0** - Servidor ASGI
- **PostgreSQL + PostGIS** - Base de datos
- **Redis** - Backend de canales para WebSockets
- **Celery** - Tareas asíncronas (si está configurado)

## 🎯 Próximos Pasos

1. ✅ Configurar el entorno de desarrollo
2. ✅ Ejecutar el servidor con Daphne
3. 📖 Revisar la documentación de la API
4. 🔗 Conectar las aplicaciones frontend
5. 🧪 Ejecutar tests (si están disponibles)

## 📚 Recursos Adicionales

- [Documentación de Django](https://docs.djangoproject.com/)
- [Documentación de Django Channels](https://channels.readthedocs.io/)
- [Documentación de Daphne](https://github.com/django/daphne)

---

**¿Problemas?** Revisa la sección de Troubleshooting o abre un issue en el repositorio.

