#!/bin/bash

# Script para iniciar ngrok y exponer el servidor Django para pruebas de webhook

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Iniciando ngrok para webhook de Mercado Pago${NC}"
echo ""

# Verificar que ngrok está instalado
if ! command -v ngrok &> /dev/null; then
    echo -e "${YELLOW}❌ ngrok no está instalado${NC}"
    echo "Instalar con: brew install ngrok/ngrok/ngrok"
    exit 1
fi

# Puerto por defecto (Daphne normalmente usa 8000)
PORT=${1:-8000}

echo -e "${GREEN}📡 Exponiendo servidor en puerto ${PORT}${NC}"
echo -e "${BLUE}Nota: Asegúrate de que Daphne esté corriendo en este puerto${NC}"
echo ""

# Verificar que ngrok esté autenticado
if ! ngrok config check &>/dev/null; then
    echo -e "${YELLOW}⚠️  ngrok no está autenticado${NC}"
    echo "Ejecuta: ngrok config add-authtoken TU_TOKEN"
    exit 1
fi

# Iniciar ngrok en segundo plano
ngrok http $PORT > /tmp/ngrok.log 2>&1 &

# Guardar el PID
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
        echo "O ejecuta manualmente:"
        echo "ngrok http $PORT"
        echo ""
        echo -e "${YELLOW}Luego copia la URL HTTPS mostrada y úsala para configurar el webhook${NC}"
        exit 1
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
echo -e "${YELLOW}🛑 Para detener ngrok, presiona Ctrl+C o ejecuta:${NC}"
echo "kill $(cat /tmp/ngrok.pid)"
echo ""

# Función para limpiar al salir
cleanup() {
    echo ""
    echo -e "${YELLOW}🛑 Deteniendo ngrok...${NC}"
    kill $NGROK_PID 2>/dev/null
    rm -f /tmp/ngrok.pid /tmp/ngrok.log
    echo -e "${GREEN}✅ ngrok detenido${NC}"
    exit 0
}

# Capturar Ctrl+C
trap cleanup INT TERM

# Mantener el script corriendo
echo -e "${BLUE}Presiona Ctrl+C para detener ngrok${NC}"
wait $NGROK_PID

