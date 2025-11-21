#!/bin/bash
# Script para cambiar a modo producción usando el token del MCP

echo "⚠️  ADVERTENCIA: Esto cambiará el modo a PRODUCCIÓN"
echo "   El token del MCP es de producción según Mercado Pago"
echo ""
read -p "¿Continuar? (s/n): " respuesta

if [ "$respuesta" != "s" ]; then
    echo "Operación cancelada"
    exit 0
fi

cd "$(dirname "$0")"

# Backup del .env
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)

# Actualizar .env
sed -i '' 's/MERCADOPAGO_MODE=test/MERCADOPAGO_MODE=production/' .env

echo "✅ MERCADOPAGO_MODE cambiado a production"
echo ""
echo "📝 Próximos pasos:"
echo "1. Reinicia Daphne: pkill -f daphne && daphne -b 0.0.0.0 -p 8000 mecanimovilapp.asgi:application"
echo "2. Elimina todas las tarjetas guardadas: python eliminar_tarjetas_antiguas.py"
echo "3. Agrega una nueva tarjeta desde la app"
echo ""
echo "⚠️  NOTA: Ahora estás usando modo PRODUCCIÓN real"

