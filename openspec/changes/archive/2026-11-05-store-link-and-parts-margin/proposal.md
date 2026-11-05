## Why

En la cotización de un Citroën Berlingo la casa sugerida es Adriazola, pero `url_referencia` abre otra tienda. El taller no puede fiarse del precio ni ver cuánto gana cuando sube lo que cobra al cliente.

## What Changes

- `url_referencia`, `tienda_referencia` y `precio_verificado_clp` salen siempre de la misma ficha. La casa donde conviene comprar va aparte, como `casa_sugerida`. Si el precio no se verificó ahí, la nota lo dice.
- La búsqueda intenta primero el sitio de esa casa (cuando publica catálogo) y solo usa otra tienda si ahí no hay ficha.
- El PDF de la casa muestra la tienda real del enlace, no la casa sugerida.
- La API del taller expone costo, cobrado, margen en CLP y % por repuesto, y el total de la cotización. La vista pública del cliente no los recibe.

## Capabilities

### New Capabilities

### Modified Capabilities

- `orden-compra-repuestos`: la ficha verificada es de una sola tienda, y el taller ve la ganancia de los repuestos.

## Impact

- Código: enriquecimiento, búsqueda web, PDF de compra y `CotizacionCanalSerializer`. Sin endpoint nuevo y sin migración.
- `costo_repuestos_clp` y `total_clp` que ve el cliente no cambian.

## Non-goals

- No reescribir el precio cobrado al cliente ni la mano de obra.
- No publicar costo ni margen en el link público.
- No agregar un reporte por periodo: el total es por cotización.
