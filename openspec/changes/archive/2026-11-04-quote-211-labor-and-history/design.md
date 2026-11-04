## Context

`texto_pedido_taller` junta el nombre del servicio y el detalle con `|`. «Mantención» queda como un trozo propio y `interpretar_pedido_taller` lo convierte en faena porque `es_solo_mano` es verdadero. El detalle «mantención con pastillas de freno» también queda como faena, con ese título, además de las tres faenas concretas. Son cinco líneas.

El precio de historial guarda `proveedor_nombre` «Historial del taller» y `fuente_marketplace` `historial`. `_aplicar_seleccion_casa_repuestos` lo trata como casa (`_casa_es_tienda` es verdadero) y `_aplicar_prioridad_de_taller` se salta la línea, así que no la mueve a Indra. El PDF agrupa por `casa_repuesto_nombre` o `proveedor_nombre`. La sucursal que la línea ya tenía (Indra, La Florida) se imprime otra vez bajo ese título.

El total del cliente suma `precio_unitario_clp` y no depende del nombre de la casa.

## Goals / Non-Goals

**Goals:**

- Cuatro faenas cuando el nombre del servicio es genérico y el detalle ya lista los trabajos.
- Titular «Cambio de pastillas de freno» la mantención que nombra esa pieza.
- Comprar esa pieza en la especialista de la marca. El historial solo aporta la referencia.
- Un solo grupo y una sola sucursal en el PDF.

**Non-Goals:**

- Cambiar totales, IVA o el unitario que ya salió del historial.
- Tratar el catálogo publicado del taller como historial.
- Aceptar una ficha web que no pasa las compuertas.

## Decisions

1. **El rótulo se descarta al final de la lectura, no al unir el texto.** «Mantención» sola, sin otros trabajos, sigue siendo la única faena. Si hay al menos un trabajo concreto, se quita el rótulo cuyo texto es solo «Mantención» o «Servicio» (y un calificativo vacío: general, preventiva, básica). Una revisión o una alineación no son rótulos.

2. **La mantención que nombra una pieza se titula «Cambio de» esa pieza.** El objeto sale de `_objeto_comprable`. «Mantención con pastillas de freno» y «Mantención: pastillas de freno» quedan «Cambio de pastillas de freno». El precio de la línea del modelo que habla de esas pastillas sigue calzando por tokens.

3. **El historial no es casa.** `_casa_es_tienda` rechaza la etiqueta. `_aplicar_prioridad_de_taller` no se salta `fuente=historial`: deja la casa en la especialista, `precio_a_consultar` verdadero, y `referencia_tienda` «historial del taller» con el unitario. No pasa por `monto_por_unidad_citable`, porque no es una ficha web. `fuente_marketplace` sigue en `historial` para no volver a buscar ni borrar el unitario.

4. **El PDF no confía en lo ya guardado.** Si la casa o el proveedor es la etiqueta de historial, el grupo usa la especialista de la marca. Dos grupos con la misma sucursal se fusionan. El precio de esa línea dice «A consultar. Referencia: historial del taller $X.» y no «Referencia en Historial del taller».

## Risks / Trade-offs

- [Un pedido que solo dice «Mantención» se queda en una línea] → El descarte solo corre cuando hay otra faena.
- [La nota de Indra cita un precio viejo del taller] → Es referencia, no el precio de la casa. El PDF lo dice «A consultar».
- [Una cotización ya guardada sigue con la etiqueta] → El PDF reagrupa al imprimir. El borrador nuevo sale de la selección de casa.

## Migration Plan

Sin migración. El cambio entra con el deploy del servicio web. Rollback: revertir el commit.

## Open Questions

Ninguna. El monto de referencia es el unitario ya guardado del historial.
