#!/usr/bin/env bash
# Script completo para verificar que todo funciona en producción (Render)
# Uso: ./scripts/verificar_produccion_completo.sh

set -e  # Salir si hay errores

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# URL de producción
API_URL="${API_URL:-https://mecanimovil-api.onrender.com}"
API_ENDPOINT="${API_URL}/api"

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  🔍 Verificación Completa de Producción (Render)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Contador de errores
ERRORS=0
WARNINGS=0

# Función para verificar endpoint
check_endpoint() {
    local endpoint=$1
    local description=$2
    local expected_status=${3:-200}
    
    echo -e "${YELLOW}📡 Verificando: ${description}${NC}"
    echo "   URL: ${endpoint}"
    
    response=$(curl -s -w "\n%{http_code}" -X GET "${endpoint}" --max-time 15 2>&1)
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    # Verificar si curl falló completamente
    if [ "$http_code" = "000" ] || [ -z "$http_code" ]; then
        echo -e "${RED}   ❌ ERROR: No se pudo conectar${NC}"
        echo "   Posibles causas:"
        echo "   - El servicio no está disponible"
        echo "   - Problema de conectividad"
        echo "   - El servicio está iniciando (espera 1-2 minutos)"
        ((ERRORS++))
        return 1
    fi
    
    if [ "$http_code" = "$expected_status" ]; then
        echo -e "${GREEN}   ✅ OK (HTTP ${http_code})${NC}"
        if [ ! -z "$body" ] && [ "$body" != "000" ]; then
            echo "   Response: ${body:0:100}"
        fi
        return 0
    else
        echo -e "${RED}   ❌ ERROR (HTTP ${http_code})${NC}"
        if [ ! -z "$body" ] && [ "$body" != "000" ]; then
            echo "   Response: ${body:0:200}"
        fi
        ((ERRORS++))
        return 1
    fi
}

# Función para verificar headers CORS
check_cors() {
    local endpoint=$1
    
    echo -e "${YELLOW}🌐 Verificando CORS...${NC}"
    
    # Hacer request con origen
    cors_response=$(curl -s -I -X OPTIONS "${endpoint}" \
        -H "Origin: expo://localhost" \
        -H "Access-Control-Request-Method: GET" \
        --max-time 10 || echo "")
    
    if echo "$cors_response" | grep -qi "access-control-allow-origin"; then
        echo -e "${GREEN}   ✅ CORS configurado correctamente${NC}"
        echo "$cors_response" | grep -i "access-control" | head -3
        return 0
    else
        echo -e "${YELLOW}   ⚠️  CORS headers no encontrados (puede ser normal para apps móviles)${NC}"
        ((WARNINGS++))
        return 0
    fi
}

# Función para verificar servicio Render
check_render_service() {
    local service_name=$1
    local description=$2
    
    echo -e "${YELLOW}🔧 Verificando servicio: ${description}${NC}"
    echo "   Nombre: ${service_name}"
    echo -e "${YELLOW}   ℹ️  Verifica manualmente en Render Dashboard que esté 'Live'${NC}"
    ((WARNINGS++))
}

# ============================================
# VERIFICACIONES
# ============================================

echo -e "${BLUE}1️⃣  Verificando API Principal${NC}"
echo ""

# Health check
check_endpoint "${API_ENDPOINT}/hello/" "Health Check Endpoint"

echo ""

# Verificar CORS
check_cors "${API_ENDPOINT}/hello/"

echo ""
echo -e "${BLUE}2️⃣  Verificando Endpoints Principales${NC}"
echo ""

# Endpoints comunes (ajusta según tu API)
check_endpoint "${API_ENDPOINT}/hello/" "Hello Endpoint"
# Agrega más endpoints según necesites
# check_endpoint "${API_ENDPOINT}/auth/login/" "Login Endpoint" 405  # Puede ser 405 si requiere POST

echo ""
echo -e "${BLUE}3️⃣  Verificando Servicios Render${NC}"
echo ""

check_render_service "mecanimovil-api" "API Principal (Django)"
check_render_service "mecanimovil-db" "Base de Datos (PostgreSQL)"
check_render_service "mecanimovil-redis" "Redis (Cache/Broker)"
check_render_service "mecanimovil-celery-worker" "Celery Worker"
check_render_service "mecanimovil-celery-beat" "Celery Beat"

echo ""
echo -e "${BLUE}4️⃣  Verificando Conectividad de Red${NC}"
echo ""

# Verificar que el dominio resuelve
echo -e "${YELLOW}🌍 Verificando DNS...${NC}"
if ping -c 1 -W 2 mecanimovil-api.onrender.com > /dev/null 2>&1; then
    echo -e "${GREEN}   ✅ Dominio resuelve correctamente${NC}"
else
    echo -e "${YELLOW}   ⚠️  No se pudo hacer ping (puede ser normal, Render bloquea ICMP)${NC}"
    ((WARNINGS++))
fi

# Verificar SSL
echo -e "${YELLOW}🔒 Verificando SSL...${NC}"
ssl_check=$(echo | openssl s_client -connect mecanimovil-api.onrender.com:443 -servername mecanimovil-api.onrender.com 2>/dev/null | grep -i "verify return code" || echo "")
if [ ! -z "$ssl_check" ]; then
    echo -e "${GREEN}   ✅ SSL configurado${NC}"
else
    echo -e "${YELLOW}   ⚠️  No se pudo verificar SSL (puede requerir openssl)${NC}"
    ((WARNINGS++))
fi

echo ""
echo -e "${BLUE}5️⃣  Información de Configuración${NC}"
echo ""

echo -e "${YELLOW}📋 URLs Importantes:${NC}"
echo "   API Base: ${API_URL}"
echo "   API Endpoint: ${API_ENDPOINT}"
echo "   Health Check: ${API_ENDPOINT}/hello/"

echo ""
echo -e "${YELLOW}📝 Próximos Pasos:${NC}"
echo "   1. Verifica en Render Dashboard que todos los servicios estén 'Live'"
echo "   2. Revisa los logs de cada servicio para verificar que no hay errores"
echo "   3. Configura las apps móviles para usar: ${API_ENDPOINT}"
echo "   4. Prueba la conexión desde las apps móviles"

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"

# Resumen final
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ Verificación completada: ${ERRORS} errores, ${WARNINGS} advertencias${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}⚠️  Revisa las advertencias arriba${NC}"
    fi
    exit 0
else
    echo -e "${RED}❌ Verificación completada con errores: ${ERRORS} errores, ${WARNINGS} advertencias${NC}"
    exit 1
fi
