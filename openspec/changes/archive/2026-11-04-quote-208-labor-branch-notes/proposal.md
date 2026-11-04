## Why

La cotización 208 (CJXP98, pastillas, aceite y filtro, bujías y filtro de aire) perdió dos faenas de mano de obra, dijo que Indra tiene todos los repuestos sin catálogo, eligió la sucursal de Santiago Centro aunque el taller está en La Florida, y subió el precio asumido de las bujías por encima de su propia banda.

## What Changes

- Cada trabajo que el taller pidió en la misma frase tiene su línea de mano de obra, aunque no repita el verbo.
- «Tiene todos» solo si hay ficha con precio de esa casa en cada línea. Sin catálogo, la nota pide consultar disponibilidad y deja la referencia de la tienda validada de esa línea.
- La sucursal es la de la comuna del taller (calle, número y comuna configurados). Sin dirección, queda la primera sucursal.
- Una bujía asumida, sin tienda, no puede quedar sobre el techo por unidad de su propia banda.

## Capabilities

### New Capabilities

- (ninguna)

### Modified Capabilities

- `casas-especialistas`: sucursal por la dirección del taller; no afirmar stock sin ficha.
- `cotizacion-notas`: la nota a consultar nombra la referencia de esa línea y no dice «tiene todos» sin stock verificado.
- `orden-compra-repuestos`: el PDF usa la sucursal de la comuna del taller.

## Impact

- `separar_pedido_taller.py`, `casas_especialistas.py`, `generador.py`, `enriquecer_repuestos.py`, `resolver_precio.py`, `orden_compra_pdf.py`.
- Sin migración.
