## Why

El cotizador elige como si todas las tiendas fueran un listado web. Un taller en Santiago va primero a la casa especialista de la marca (Indra para Fiat, Adriazola o Comauto para Peugeot/Citroën) y solo usa Mercado Libre cuando ninguna casa física tiene la pieza. Esas casas no salen: Indra no publica precios por ficha, y Adriazola y Comauto no estaban en la lista.

## What Changes

- Perfil de casa: marcas, tienda física, sucursales (dirección y comuna), sitio, teléfono público y si tiene catálogo con precios.
- Sumar casas especialistas reales de Santiago y consultar su sitio cuando el catálogo existe. Si no hay precios, recomendar la casa con «precio a consultar» sin inventar un monto.
- Prioridad de taller: especialista de la marca (original/OEM primero), una sola casa que cubra toda la cotización, casa física cerca de la comuna del taller, y tienda solo en línea al final, etiquetada.
- La línea de origen del precio muestra el nombre de la casa, no el slug.
- PDF «Orden de compra de repuestos» para llevar a la casa: taller, fecha, vehículo, piezas con cantidad y especificación, casa sugerida con dirección y teléfono, precio de referencia. Sin mano de obra ni margen al cliente.

## Capabilities

### New Capabilities

- `casas-especialistas`: perfiles, prioridad de selección y recomendación sin precio inventado.
- `orden-compra-repuestos`: PDF de compra para el taller.

### Modified Capabilities

- `cotizacion-notas`: la nota dice por qué se eligió la casa, y el origen del precio usa el nombre humano.

## Impact

- API: `GET /ordenes/cotizaciones-canal/{id}/orden-compra-pdf/`.
- Búsqueda web: una consulta `site:` extra solo para casas con catálogo. Las compuertas de modelo, año, motor y banda no cambian.
- Sin migración: los perfiles viven en código y el JSON de repuestos gana campos opcionales.
- App prov: botón «PDF para casa de repuestos» en el editor y el detalle.

## Non-goals

- No inventar tiendas, direcciones ni teléfonos.
- No scrapear portales que piden clave.
- No cambiar el precio que ve el cliente ni el margen.
- No geocodificar distancia en metros: la cercanía es la comuna del taller cuando está configurada.
