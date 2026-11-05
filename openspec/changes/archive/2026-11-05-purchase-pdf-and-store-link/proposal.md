## Why

La orden de compra sale como una lista de párrafos, y la app de proveedores no tiene un campo estable para abrir la ficha donde se verificó el precio. El taller necesita un documento para llevar a la casa y un enlace «Ver en tienda».

## What Changes

- El PDF `GET /api/ordenes/cotizaciones-canal/{id}/orden-compra-pdf/` se redibuja como documento: identidad del taller, título, fecha y número, ficha del vehículo, una sección por casa con tabla y enlace a la ficha cuando existe.
- Cada repuesto de la respuesta de cotización del taller expone `url_referencia`, `tienda_referencia` y `precio_verificado_clp`.
- La vista pública del cliente no recibe esos campos.
- No cambia la mano de obra, el total ni el precio que ve el cliente.

## Capabilities

### New Capabilities

- Ninguna.

### Modified Capabilities

- `orden-compra-repuestos`: el PDF pasa a ser un documento con tabla por casa, y la línea de la API del taller declara la ficha verificada.

## Impact

- Código: `orden_compra_pdf.py`, `serializers_cotizacion_canal.py`, `enriquecer_repuestos.py` (la ficha verificada).
- API: el GET de la cotización del taller agrega tres campos en cada repuesto. No hay endpoint nuevo. El PDF de orden de compra cambia de presentación, no de permiso.
- Base de datos: no requiere migración. Los campos se calculan al leer la cotización.

## Non-goals

- No se rediseña el PDF que ve el cliente.
- No se inventan horarios, sucursales ni precios de una casa.
- No se publica la URL de la ficha en el link público del cliente.
