## Context

`referencia_de_linea` puede poner en `tienda_referencia` la casa asignada (Adriazola) y en `url_referencia` la primera URL, que es de otra tienda. `especialista_de_la_ficha` también acepta el nombre de la casa aunque el enlace sea otro sitio, y entonces la línea deja de estar «a consultar». La búsqueda `site:` de la especialista corre después, y se salta si ya hubo un resultado.

`precio_unitario_clp` es lo que se cobra. El costo de compra está en la ficha verificada o en la referencia, y se pierde si una edición pisa esos campos.

## Goals / Non-Goals

**Goals:**

- Los tres campos de la ficha describen el mismo enlace.
- `casa_sugerida` es la casa de compra. `nota_referencia` avisa cuando el precio no se verificó ahí.
- El PDF nombra la tienda del enlace.
- El margen se recalcula al leer, con el costo congelado antes de cambiar el precio cobrado.

**Non-Goals:**

- No cambiar `costo_repuestos_clp` (sigue siendo la suma cobrada por repuestos).
- No crear un resumen por vehículo o por periodo.

## Decisions

1. Una ficha de la casa especialista cuenta solo si el host del enlace es el de esa casa. El nombre asignado no alcanza.
2. La búsqueda consulta primero `site:` del catálogo de la especialista. Si esa ficha pasa las compuertas y trae precio, no se sigue con otras tiendas.
3. El costo de la línea es, en orden: `costo_unitario_clp` ya guardado, el precio verificado de la ficha, la referencia, el precio de marketplace. Si no hay ninguno, el costo es el precio cobrado y el margen es 0. Al confirmar o editar, se congela el costo anterior.
4. El margen en CLP de la línea es `(cobrado − costo) × cantidad`. El porcentaje es sobre el precio cobrado. Los totales de la cotización suman esas líneas.

## Risks / Trade-offs

- [La primera consulta `site:` gasta una búsqueda más por pieza] → Solo si la casa publica catálogo, y se corta cuando ya hay ficha con precio.
- [Un costo congelado viejo no sigue una ficha nueva] → Se congela solo cuando todavía no hay `costo_unitario_clp`.
