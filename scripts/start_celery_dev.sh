#!/bin/bash

# Script para iniciar Celery Worker y Beat en desarrollo local (macOS/Linux)
# En producción, estos procesos se gestionan con Supervisor

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Iniciando Celery para desarrollo${NC}"
echo ""

# Cambiar al directorio del backend
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
cd "$BACKEND_DIR"

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

# Verificar que Celery esté instalado
if ! command -v celery &> /dev/null; then
    echo -e "${RED}❌ Error: Celery no está instalado${NC}"
    echo "Instalando Celery..."
    pip install celery==5.3.4 redis==5.0.1
fi

# Verificar que Redis esté corriendo
echo -e "${BLUE}🔍 Verificando Redis...${NC}"
if ! redis-cli ping >/dev/null 2>&1; then
    echo -e "${RED}❌ Error: Redis no está corriendo${NC}"
    echo ""
    echo "Inicia Redis con uno de estos comandos:"
    echo "  - macOS: brew services start redis"
    echo "  - Linux: sudo systemctl start redis"
    echo "  - Manual: redis-server"
    exit 1
fi
echo -e "${GREEN}✅ Redis está corriendo${NC}"

# Verificar configuración de Celery
echo -e "${BLUE}🔍 Verificando configuración de Celery...${NC}"
if ! python -c "from mecanimovilapp.celery import app; print('OK')" 2>/dev/null; then
    echo -e "${RED}❌ Error: No se pudo cargar la configuración de Celery${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Configuración de Celery OK${NC}"

# Función para limpiar procesos al salir
cleanup() {
    echo ""
    echo -e "${YELLOW}🛑 Deteniendo Celery...${NC}"
    if [ ! -z "$CELERY_WORKER_DEFAULT_PID" ]; then
        kill $CELERY_WORKER_DEFAULT_PID 2>/dev/null
    fi
    if [ ! -z "$CELERY_WORKER_HEAVY_PID" ]; then
        kill $CELERY_WORKER_HEAVY_PID 2>/dev/null
    fi
    if [ ! -z "$CELERY_BEAT_PID" ]; then
        kill $CELERY_BEAT_PID 2>/dev/null
    fi
    exit 0
}

trap cleanup INT TERM

# Opciones: worker, beat, o ambos
MODE=${1:-both}

if [ "$MODE" == "worker" ] || [ "$MODE" == "both" ]; then
    echo ""
    echo -e "${GREEN}👷 Iniciando Celery Workers optimizados...${NC}"
    echo ""
    
    # Worker para tareas ligeras (default queue)
    echo -e "${BLUE}📦 Iniciando worker para cola 'default' (tareas ligeras)...${NC}"
    celery -A mecanimovilapp worker \
        --loglevel=info \
        --queues=default \
        --concurrency=4 \
        --max-tasks-per-child=100 \
        --max-memory-per-child=512000 \
        --prefetch-multiplier=4 \
        --hostname=worker-default@%h &
    CELERY_WORKER_DEFAULT_PID=$!
    echo -e "${GREEN}✅ Worker 'default' iniciado (PID: $CELERY_WORKER_DEFAULT_PID)${NC}"
    echo ""
    
    # Worker para tareas pesadas (heavy queue)
    echo -e "${BLUE}📦 Iniciando worker para cola 'heavy' (tareas pesadas)...${NC}"
    celery -A mecanimovilapp worker \
        --loglevel=info \
        --queues=heavy \
        --concurrency=2 \
        --max-tasks-per-child=50 \
        --max-memory-per-child=512000 \
        --prefetch-multiplier=2 \
        --hostname=worker-heavy@%h &
    CELERY_WORKER_HEAVY_PID=$!
    echo -e "${GREEN}✅ Worker 'heavy' iniciado (PID: $CELERY_WORKER_HEAVY_PID)${NC}"
    echo ""
    
    echo -e "${GREEN}✅ Todos los Celery Workers iniciados${NC}"
fi

if [ "$MODE" == "beat" ] || [ "$MODE" == "both" ]; then
    echo ""
    echo -e "${GREEN}⏰ Iniciando Celery Beat...${NC}"
    celery -A mecanimovilapp beat --loglevel=info &
    CELERY_BEAT_PID=$!
    echo -e "${GREEN}✅ Celery Beat iniciado (PID: $CELERY_BEAT_PID)${NC}"
fi

echo ""
echo -e "${BLUE}📊 Celery está corriendo${NC}"
echo -e "${BLUE}💡 Para detener, presiona Ctrl+C${NC}"
echo ""
echo -e "${BLUE}📋 Configuración de Workers:${NC}"
echo "  - Worker 'default': 4 procesos, prefetch=4, max-memory=512MB"
echo "  - Worker 'heavy': 2 procesos, prefetch=2, max-memory=512MB"
echo ""
echo "Comandos útiles:"
echo "  - Ver tareas activas: celery -A mecanimovilapp inspect active"
echo "  - Ver estadísticas: celery -A mecanimovilapp inspect stats"
echo "  - Ver colas: celery -A mecanimovilapp inspect reserved"
echo "  - Limpiar colas: celery -A mecanimovilapp purge"
echo ""

# Esperar a que los procesos terminen
wait

