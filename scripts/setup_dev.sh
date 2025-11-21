#!/bin/bash

# Script de configuración inicial para desarrollo
# Este script configura el entorno de desarrollo desde cero

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}🔧 Configurando entorno de desarrollo${NC}"
echo ""

# Verificar que estamos en el directorio correcto
if [ ! -f "manage.py" ]; then
    echo -e "${RED}❌ Error: No se encontró manage.py${NC}"
    echo "Ejecuta este script desde el directorio mecanimovil-backend"
    exit 1
fi

# 1. Crear entorno virtual si no existe
if [ ! -d "venv" ]; then
    echo -e "${BLUE}📦 Creando entorno virtual...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}✅ Entorno virtual creado${NC}"
else
    echo -e "${GREEN}✅ Entorno virtual ya existe${NC}"
fi

# 2. Activar entorno virtual
echo -e "${BLUE}🔄 Activando entorno virtual...${NC}"
source venv/bin/activate

# 3. Actualizar pip
echo -e "${BLUE}📦 Actualizando pip...${NC}"
pip install --upgrade pip

# 4. Instalar dependencias
echo -e "${BLUE}📦 Instalando dependencias...${NC}"
pip install -r requirements.txt

echo -e "${GREEN}✅ Dependencias instaladas${NC}"

# 5. Crear archivo .env si no existe
if [ ! -f ".env" ]; then
    echo -e "${BLUE}📝 Creando archivo .env de ejemplo...${NC}"
    cat > .env << EOF
# Django Settings
DEBUG=True
SECRET_KEY=django-insecure-k#t34sc+!o_g&y#d^f-jxfh%7u*6ya!rco%v8!c6(0ot8*6u@^
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

# Database (PostgreSQL)
DB_NAME=mecanimovil
DB_USER=sebastianm
DB_PASSWORD=
DB_HOST=localhost
DB_PORT=5432

# Redis (para WebSockets)
REDIS_URL=redis://localhost:6379/0

# Mercado Pago (usar credenciales de prueba para desarrollo)
MERCADOPAGO_ACCESS_TOKEN=TU_ACCESS_TOKEN_AQUI
MERCADOPAGO_PUBLIC_KEY=TU_PUBLIC_KEY_AQUI
MERCADOPAGO_WEBHOOK_SECRET=a7934fae72aca801d2bd08aeaa79b0d650c7900c0def8aa559583934d9de44ee

# Email (opcional)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EOF
    echo -e "${GREEN}✅ Archivo .env creado${NC}"
    echo -e "${YELLOW}⚠️  Revisa y configura las variables en .env según tu entorno${NC}"
else
    echo -e "${GREEN}✅ Archivo .env ya existe${NC}"
fi

# 6. Aplicar migraciones
echo -e "${BLUE}🔄 Aplicando migraciones...${NC}"
python manage.py migrate

# 7. Crear superusuario si no existe
echo ""
read -p "¿Deseas crear un superusuario? (s/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[SsYy]$ ]]; then
    python manage.py createsuperuser
fi

# 8. Dar permisos de ejecución a los scripts
chmod +x start_dev.sh
chmod +x setup_dev.sh

echo ""
echo -e "${GREEN}✅ Configuración completada${NC}"
echo ""
echo -e "${BLUE}📋 Próximos pasos:${NC}"
echo "  1. Configura las variables de entorno en .env"
echo "  2. Asegúrate de que PostgreSQL esté corriendo"
echo "  3. Asegúrate de que Redis esté corriendo (para WebSockets)"
echo "  4. Ejecuta './start_dev.sh' para iniciar el servidor de desarrollo"
echo ""
echo -e "${GREEN}🚀 Para iniciar el servidor:${NC}"
echo "  ./start_dev.sh"

