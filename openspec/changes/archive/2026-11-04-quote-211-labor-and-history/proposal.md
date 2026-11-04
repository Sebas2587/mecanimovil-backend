## Why

La cotización 211 (servicio «Mantención», detalle «mantención con pastillas de freno, cambio de aceite y filtro, bujías y filtro de aire») volvió a salir con cinco líneas de mano de obra y con las pastillas agrupadas como si «Historial del taller» fuera una casa. El nombre del servicio no es un trabajo, y el historial es un precio de referencia, no una tienda.

## What Changes

- El rótulo genérico «Mantención» (el nombre del servicio) no se agrega como línea de mano de obra cuando el detalle ya nombra trabajos concretos.
- «Mantención con pastillas de freno» se normaliza a «Cambio de pastillas de freno». El pedido queda en cuatro faenas.
- El historial del taller no se usa como casa. Las pastillas se agrupan bajo la especialista recomendada (Indra) y, si hay monto, la nota y el PDF dicen «Referencia: historial del taller $40.000».
- El PDF de compra no imprime «Historial del taller» como tienda ni repite la misma sucursal en dos grupos.
- El precio que ve el cliente y el total con IVA no cambian.

## Capabilities

### New Capabilities

- Ninguna.

### Modified Capabilities

- `mano-obra-pedido`: el nombre del servicio no crea una faena extra, y una mantención que nombra una pieza se titula como cambio de esa pieza.
- `orden-compra-repuestos`: el historial no es una casa; la pieza va con la especialista y la sucursal se imprime una sola vez.

## Impact

- Código: `separar_pedido_taller.py`, `generador.py` (`_aplicar_prioridad_de_taller`), `orden_compra_pdf.py`, y la nota de referencia en `enriquecer_repuestos.py`.
- API: no hay endpoints nuevos ni cambios de contrato. El PDF de orden de compra (`GET .../orden-compra-pdf/`) deja de titular un grupo «Historial del taller».
- Base de datos: no requiere migración.
- Tests: regresión de la cotización 211 en mano de obra y en el PDF de compra.

## Non-goals

- No se recalculan los totales ni el IVA.
- El catálogo publicado del taller sigue siendo una fuente propia del taller, no se reinterpreta como historial.
- No se cambia la compuerta de fichas web ni se inventa un precio de Indra.
