## Why

En el borrador «TEST Cotización IA 11» (CJXP98) el editor del taller ve la ficha Entretuercas «Bujía Iridio Champion Fiat Bravo 1.4 2007-2014 x4» a $15.826, y el cobrado ya es $3.956 por bujía, pero la línea no trae `url_referencia` ni `tienda_referencia`. La banda guardada en la línea es el precio del pack, así que la ficha compatible se descarta al leer el detalle y el link no sale en `GET /api/ordenes/cotizaciones-canal/{id}/`.

## What Changes

- Una ficha del mismo auto, cuyo precio por unidad ya es el cobrado, se cita: link, tienda y `precio_verificado_clp` por unidad. La banda del pack no la esconde.
- Un precio ya guardado por unidad no se vuelve a partir porque el título diga x4.
- Ese detalle (y el mismo serializer en generar-ia, guardar y reabrir) incluye `validacion_estado`, `validacion_motivo`, `alertas` y `alertas_validacion`. La vista previa del cliente no.

## Capabilities

### New Capabilities

### Modified Capabilities

- `orden-compra-repuestos`: el detalle del taller cita la ficha compatible aunque la banda de la línea sea el pack.

## Impact

- Código: la validación al serializar la cotización del taller. Sin migración y sin otra búsqueda web.

## Non-goals

- No cambiar la vista pública del cliente.
- No volver a buscar la ficha en la web al abrir el borrador.
