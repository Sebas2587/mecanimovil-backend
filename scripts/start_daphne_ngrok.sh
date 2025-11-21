#!/bin/bash

# Script para iniciar Daphne y ngrok juntos para pruebas de webhook

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Iniciando Daphne y ngrok para webhook de Mercado Pago${NC}"
echo ""

# Verificar que estamos en el directorio correcto
if [ ! -f "manage.py" ]; then
    echo -e "${RED}❌ Error: No se encontró manage.py${NC}"
    echo "Ejecuta este script desde el directorio mecanimovil-backend"
    exit 1
fi

# Verificar que ngrok está instalado
if ! command -v ngrok &> /dev/null; then
    echo -e "${RED}❌ ngrok no está instalado${NC}"
    echo "Instalar con: brew install ngrok/ngrok/ngrok"
    exit 1
fi

# Puerto por defecto
PORT=${1:-8000}

# Verificar que el puerto no esté en uso
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null ; then
    echo -e "${YELLOW}⚠️  El puerto ${PORT} ya está en uso${NC}"
    echo "¿Está Daphne ya corriendo?"
    read -p "¿Deseas continuar de todas formas? (s/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[SsYy]$ ]]; then
        exit 1
    fi
fi

# Función para limpiar procesos al salir
cleanup() {
    echo ""
    echo -e "${YELLOW}🛑 Deteniendo procesos...${NC}"
    
    # Detener ngrok si está corriendo
    if [ -f /tmp/ngrok.pid ]; then
        kill $(cat /tmp/ngrok.pid) 2>/dev/null
        rm -f /tmp/ngrok.pid
    fi
    
    # Detener Daphne si está corriendo
    if [ -f /tmp/daphne.pid ]; then
        kill $(cat /tmp/daphne.pid) 2>/dev/null
        rm -f /tmp/daphne.pid
    fi
    
    echo -e "${GREEN}✅ Procesos detenidos${NC}"
    exit 0
}

# Capturar Ctrl+C
trap cleanup INT TERM

# Iniciar Daphne
echo -e "${GREEN}📦 Iniciando Daphne en puerto ${PORT}...${NC}"
daphne -b 0.0.0.0 -p $PORT mecanimovilapp.asgi:application > /tmp/daphne.log 2>&1 &
DAPHNE_PID=$!
echo $DAPHNE_PID > /tmp/daphne.pid

# Esperar un momento para que Daphne se inicie
sleep 2

# Verificar que Daphne está corriendo
if ! kill -0 $DAPHNE_PID 2>/dev/null; then
    echo -e "${RED}❌ Error: No se pudo iniciar Daphne${NC}"
    echo "Revisa los logs en /tmp/daphne.log"
    exit 1
fi

echo -e "${GREEN}✅ Daphne iniciado correctamente (PID: $DAPHNE_PID)${NC}"
echo ""

# Verificar que ngrok esté autenticado
if ! ngrok config check &>/dev/null; then
    echo -e "${RED}❌ ngrok no está autenticado${NC}"
    echo "Ejecuta: ngrok config add-authtoken TU_TOKEN"
    exit 1
fi

# Iniciar ngrok
echo -e "${GREEN}📡 Iniciando ngrok en puerto ${PORT}...${NC}"
ngrok http $PORT > /tmp/ngrok.log 2>&1 &
NGROK_PID=$!
echo $NGROK_PID > /tmp/ngrok.pid

# Esperar un momento para que ngrok se inicialice
sleep 3

# Obtener la URL de ngrok usando el script Python
NGROK_URL=$(python3 "$(dirname "$0")/get_ngrok_url.py" 2>/dev/null)

if [ -z "$NGROK_URL" ]; then
    # Intentar método alternativo
    NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | grep -o 'https://[^"]*\.ngrok[^"]*' | head -1)
    
    if [ -z "$NGROK_URL" ]; then
        echo -e "${YELLOW}⚠️  No se pudo obtener la URL de ngrok automáticamente${NC}"
        echo ""
        echo -e "${BLUE}Por favor, ve a la interfaz web de ngrok para obtener la URL:${NC}"
        echo "http://localhost:4040"
        echo ""
        echo -e "${YELLOW}Luego copia la URL HTTPS mostrada y úsala para configurar el webhook${NC}"
        echo ""
        echo -e "${BLUE}Presiona Ctrl+C para detener ambos servicios${NC}"
        wait $NGROK_PID
        exit 0
    fi
fi

echo -e "${GREEN}✅ ngrok iniciado correctamente${NC}"
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}🔗 URL pública del servidor:${NC}"
echo -e "${BLUE}${NGROK_URL}${NC}"
echo ""
echo -e "${GREEN}🔗 URL del webhook para Mercado Pago:${NC}"
echo -e "${BLUE}${NGROK_URL}/api/mercadopago/webhook/${NC}"
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}📋 Instrucciones:${NC}"
echo "1. Copia la URL del webhook mostrada arriba"
echo "2. Ve al panel de Mercado Pago → Webhooks"
echo "3. Agrega la URL del webhook"
echo "4. Guarda la configuración"
echo ""
echo -e "${YELLOW}📊 Para ver la interfaz web de ngrok:${NC}"
echo "http://localhost:4040"
echo ""
echo -e "${YELLOW}📋 Logs de Daphne:${NC}"
echo "tail -f /tmp/daphne.log"
echo ""
echo -e "${YELLOW}🛑 Para detener ambos servicios, presiona Ctrl+C${NC}"
echo ""

# Mantener el script corriendo
wait $NGROK_PID

