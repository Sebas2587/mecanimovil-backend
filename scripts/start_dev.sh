#!/bin/bash

# Script de desarrollo local con Daphne
# Ejecuta el servidor Daphne con todas las configuraciones necesarias para desarrollo

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Iniciando servidor de desarrollo con Daphne${NC}"
echo ""

# Verificar que estamos en el directorio correcto
if [ ! -f "manage.py" ]; then
    echo -e "${RED}❌ Error: No se encontró manage.py${NC}"
    echo "Ejecuta este script desde el directorio mecanimovil-backend"
    exit 1
fi

# Verificar que el entorno virtual esté activado
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${YELLOW}⚠️  Entorno virtual no detectado${NC}"
    echo "Activando entorno virtual..."
    
    if [ -d "venv" ]; then
        source venv/bin/activate
        echo -e "${GREEN}✅ Entorno virtual activado${NC}"
    else
        echo -e "${RED}❌ Error: No se encontró el directorio venv/${NC}"
        echo "Crea el entorno virtual con: python3 -m venv venv"
        exit 1
    fi
else
    echo -e "${GREEN}✅ Entorno virtual activo: $VIRTUAL_ENV${NC}"
fi

# Puerto por defecto
PORT=${1:-8000}

# Verificar que el puerto no esté en uso
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  El puerto ${PORT} ya está en uso${NC}"
    read -p "¿Deseas continuar de todas formas? (s/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[SsYy]$ ]]; then
        exit 1
    fi
fi

# Verificar que las dependencias estén instaladas
echo -e "${BLUE}📦 Verificando dependencias...${NC}"
if ! python -c "import daphne" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  Daphne no está instalado${NC}"
    echo "Instalando dependencias..."
    pip install -r requirements.txt
fi

# Aplicar migraciones pendientes
echo -e "${BLUE}🔄 Verificando migraciones...${NC}"
python manage.py migrate --noinput

# Verificar que Redis esté corriendo (opcional, solo muestra advertencia)
if ! redis-cli ping >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Redis no está corriendo${NC}"
    echo "Los WebSockets pueden no funcionar correctamente"
    echo "Inicia Redis con: brew services start redis (macOS) o redis-server"
fi

# Función para limpiar al salir
cleanup() {
    echo ""
    echo -e "${YELLOW}🛑 Deteniendo servidor...${NC}"
    exit 0
}

trap cleanup INT TERM

# Iniciar Daphne
echo ""
echo -e "${GREEN}📡 Iniciando Daphne en http://0.0.0.0:${PORT}${NC}"
echo -e "${BLUE}💡 Para detener el servidor, presiona Ctrl+C${NC}"
echo ""

daphne -b 0.0.0.0 -p $PORT mecanimovilapp.asgi:application

