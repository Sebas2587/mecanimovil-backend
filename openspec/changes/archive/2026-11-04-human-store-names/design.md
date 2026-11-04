# Design

`_canon_nombre_tienda` ya convierte «todoauto» en «TodoAuto», pero dos huecos dejan el slug a la vista:

- `_tienda_por_dominio` devuelve el `nombre` de la lista sin pasarlo por el canon, y la caché copia `tienda` tal cual a `proveedor_nombre`.
- `sanear_notas_linea` da por buena una nota que empieza con el nombre humano. «Todoautochile: …» empieza con «todoauto», así que no se reescribe.

El canon compara el slug compacto (sin espacios) con un alias, y también si el slug es ese alias más un sufijo (`chile`, `spa`). La nota solo se conserva si el nombre humano va seguido de `:`, `,` o el fin del texto. `proveedor_nombre` y `casa_repuesto_nombre` quedan con el mismo nombre.
