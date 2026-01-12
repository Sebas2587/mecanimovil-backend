#!/bin/bash

# Script de deployment para producción de Mecanimovil
# Este script configura Redis, Django Channels y el servidor para producción

set -e  # Salir si hay algún error

echo "🚀 Iniciando deployment de Mecanimovil para producción..."

# Variables de configuración
PROJECT_DIR="/var/www/mecanimovil"
VENV_DIR="$PROJECT_DIR/venv"
BACKEND_DIR="$PROJECT_DIR/backend"
LOG_DIR="/var/log/mecanimovil"
REDIS_CONF="/etc/redis/mecanimovil.conf"
NGINX_CONF="/etc/nginx/sites-available/mecanimovil"

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Función para imprimir mensajes
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Verificar si se ejecuta como root
if [[ $EUID -ne 0 ]]; then
   print_error "Este script debe ejecutarse como root"
   exit 1
fi

# Función para instalar dependencias del sistema
install_system_dependencies() {
    print_status "Instalando dependencias del sistema..."
    
    apt-get update
    apt-get install -y \
        python3 \
        python3-pip \
        python3-venv \
        postgresql \
        postgresql-contrib \
        postgis \
        redis-server \
        nginx \
        certbot \
        python3-certbot-nginx \
        supervisor \
        git \
        curl \
        wget \
        unzip
    
    print_status "Dependencias del sistema instaladas"
}

# Función para configurar Redis
setup_redis() {
    print_status "Configurando Redis..."
    
    # Crear directorio de logs
    mkdir -p /var/log/redis
    
    # Copiar configuración de Redis
    if [ -f "$BACKEND_DIR/redis_mecanimovil.conf" ]; then
        cp "$BACKEND_DIR/redis_mecanimovil.conf" "$REDIS_CONF"
        print_status "Configuración de Redis copiada"
    else
        print_warning "Archivo de configuración de Redis no encontrado, usando configuración por defecto"
    fi
    
    # Configurar permisos
    chown redis:redis "$REDIS_CONF"
    chmod 640 "$REDIS_CONF"
    
    # Reiniciar Redis
    systemctl restart redis-server
    systemctl enable redis-server
    
    # Verificar que Redis esté funcionando
    if redis-cli ping | grep -q "PONG"; then
        print_status "Redis configurado y funcionando"
    else
        print_error "Error configurando Redis"
        exit 1
    fi
}

# Función para configurar PostgreSQL
setup_postgresql() {
    print_status "Configurando PostgreSQL..."
    
    # Crear usuario y base de datos
    sudo -u postgres psql << EOF
CREATE USER mecanimovil WITH PASSWORD 'tu_password_aqui';
CREATE DATABASE mecanimovil OWNER mecanimovil;
\c mecanimovil
CREATE EXTENSION postgis;
CREATE EXTENSION postgis_topology;
GRANT ALL PRIVILEGES ON DATABASE mecanimovil TO mecanimovil;
EOF
    
    print_status "PostgreSQL configurado"
}

# Función para configurar el entorno virtual
setup_python_environment() {
    print_status "Configurando entorno virtual de Python..."
    
    # Crear directorio del proyecto
    mkdir -p "$PROJECT_DIR"
    cd "$PROJECT_DIR"
    
    # Crear entorno virtual
    python3 -m venv "$VENV_DIR"
    
    # Activar entorno virtual
    source "$VENV_DIR/bin/activate"
    
    # Instalar dependencias
    pip install --upgrade pip
    pip install -r "$BACKEND_DIR/requirements.txt"
    
    print_status "Entorno virtual configurado"
}

# Función para configurar Django
setup_django() {
    print_status "Configurando Django..."
    
    cd "$BACKEND_DIR"
    source "$VENV_DIR/bin/activate"
    
    # Crear archivo .env para producción
    cat > .env << EOF
DEBUG=False
SECRET_KEY=tu_secret_key_aqui
DB_NAME=mecanimovil
DB_USER=mecanimovil
DB_PASSWORD=tu_password_aqui
DB_HOST=localhost
DB_PORT=5432
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=tu_redis_password_aqui
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=tu_email@gmail.com
EMAIL_HOST_PASSWORD=tu_email_password
EOF
    
    # Aplicar migraciones
    python manage.py migrate --settings=mecanimovilapp.settings_production
    
    # Recolectar archivos estáticos
    python manage.py collectstatic --noinput --settings=mecanimovilapp.settings_production
    
    # Crear superusuario si no existe
    echo "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('admin', 'admin@mecanimovil.com', 'admin123') if not User.objects.filter(username='admin').exists() else None" | python manage.py shell --settings=mecanimovilapp.settings_production
    
    print_status "Django configurado"
}

# Función para configurar Nginx
setup_nginx() {
    print_status "Configurando Nginx..."
    
    # Copiar configuración de Nginx
    if [ -f "$BACKEND_DIR/nginx_websocket_config.conf" ]; then
        cp "$BACKEND_DIR/nginx_websocket_config.conf" "$NGINX_CONF"
        print_status "Configuración de Nginx copiada"
    else
        print_warning "Archivo de configuración de Nginx no encontrado"
    fi
    
    # Crear enlace simbólico
    ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/
    
    # Verificar configuración de Nginx
    nginx -t
    
    # Reiniciar Nginx
    systemctl restart nginx
    systemctl enable nginx
    
    print_status "Nginx configurado"
}

# Función para configurar Supervisor
setup_supervisor() {
    print_status "Configurando Supervisor..."
    
    # Crear configuración de Supervisor
    cat > /etc/supervisor/conf.d/mecanimovil.conf << EOF
[program:mecanimovil_backend]
command=$VENV_DIR/bin/daphne -b 0.0.0.0 -p 8000 mecanimovilapp.asgi:application
directory=$BACKEND_DIR
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=$LOG_DIR/daphne.log
environment=DJANGO_SETTINGS_MODULE="mecanimovilapp.settings_production"

[program:mecanimovil_celery_default]
command=$VENV_DIR/bin/celery -A mecanimovilapp worker --loglevel=info --queues=default --concurrency=4 --max-tasks-per-child=100 --max-memory-per-child=512000 --prefetch-multiplier=4 --hostname=worker-default@%h
directory=$BACKEND_DIR
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=$LOG_DIR/celery_default.log
environment=DJANGO_SETTINGS_MODULE="mecanimovilapp.settings_production"

[program:mecanimovil_celery_heavy]
command=$VENV_DIR/bin/celery -A mecanimovilapp worker --loglevel=info --queues=heavy --concurrency=2 --max-tasks-per-child=50 --max-memory-per-child=512000 --prefetch-multiplier=2 --hostname=worker-heavy@%h
directory=$BACKEND_DIR
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=$LOG_DIR/celery_heavy.log
environment=DJANGO_SETTINGS_MODULE="mecanimovilapp.settings_production"

[program:mecanimovil_celery_beat]
command=$VENV_DIR/bin/celery -A mecanimovilapp beat --loglevel=info
directory=$BACKEND_DIR
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=$LOG_DIR/celery_beat.log
environment=DJANGO_SETTINGS_MODULE="mecanimovilapp.settings_production"
EOF
    
    # Crear directorio de logs
    mkdir -p "$LOG_DIR"
    chown www-data:www-data "$LOG_DIR"
    
    # Reiniciar Supervisor
    supervisorctl reread
    supervisorctl update
    supervisorctl start mecanimovil_backend
    supervisorctl start mecanimovil_celery_default
    supervisorctl start mecanimovil_celery_heavy
    supervisorctl start mecanimovil_celery_beat
    
    print_status "Supervisor configurado con workers optimizados"
    print_status "  - Worker 'default': 4 procesos, tareas ligeras"
    print_status "  - Worker 'heavy': 2 procesos, tareas pesadas"
}

# Función para configurar SSL
setup_ssl() {
    print_status "Configurando SSL con Let's Encrypt..."
    
    # Obtener certificados SSL
    certbot --nginx -d api.mecanimovil.com -d www.api.mecanimovil.com
    certbot --nginx -d app.mecanimovil.com -d www.app.mecanimovil.com
    certbot --nginx -d proveedores.mecanimovil.com -d www.proveedores.mecanimovil.com
    
    # Configurar renovación automática
    echo "0 12 * * * /usr/bin/certbot renew --quiet" | crontab -
    
    print_status "SSL configurado"
}

# Función para ejecutar pruebas
run_tests() {
    print_status "Ejecutando pruebas de configuración..."
    
    cd "$BACKEND_DIR"
    source "$VENV_DIR/bin/activate"
    
    # Probar conexión a Redis
    python -c "import redis; r = redis.Redis(); r.ping(); print('Redis OK')"
    
    # Probar conexión a PostgreSQL
    python -c "from django.db import connection; connection.ensure_connection(); print('PostgreSQL OK')"
    
    # Probar configuración de Channels
    python -c "from channels.layers import get_channel_layer; get_channel_layer(); print('Channels OK')"
    
    # Ejecutar script de configuración
    python setup_redis_production.py
    
    print_status "Pruebas completadas"
}

# Función para mostrar información final
show_final_info() {
    print_status "Deployment completado exitosamente!"
    echo ""
    echo "📋 Información del deployment:"
    echo "   - Backend: https://api.mecanimovil.com"
    echo "   - App Clientes: https://app.mecanimovil.com"
    echo "   - App Proveedores: https://proveedores.mecanimovil.com"
    echo "   - Admin Django: https://api.mecanimovil.com/admin"
    echo ""
    echo "🔧 Servicios configurados:"
    echo "   - Redis: $(systemctl is-active redis-server)"
    echo "   - Nginx: $(systemctl is-active nginx)"
    echo "   - Supervisor: $(systemctl is-active supervisor)"
    echo ""
    echo "📊 Logs disponibles en:"
    echo "   - Django: $LOG_DIR/daphne.log"
    echo "   - Celery: $LOG_DIR/celery.log"
    echo "   - Nginx: /var/log/nginx/"
    echo ""
    echo "🛠️ Comandos útiles:"
    echo "   - Ver logs: tail -f $LOG_DIR/daphne.log"
    echo "   - Reiniciar backend: supervisorctl restart mecanimovil_backend"
    echo "   - Ver estado: supervisorctl status"
    echo ""
    echo "⚠️ IMPORTANTE:"
    echo "   - Cambia las contraseñas en el archivo .env"
    echo "   - Configura las variables de entorno para producción"
    echo "   - Configura el firewall para permitir solo puertos 80, 443"
}

# Función principal
main() {
    print_status "Iniciando deployment de Mecanimovil..."
    
    install_system_dependencies
    setup_redis
    setup_postgresql
    setup_python_environment
    setup_django
    setup_nginx
    setup_supervisor
    setup_ssl
    run_tests
    show_final_info
}

# Ejecutar función principal
main "$@" 