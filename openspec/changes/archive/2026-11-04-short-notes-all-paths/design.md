# Design

## Dónde se arma hoy

- `_aviso_sin_ficha` ya devuelve la nota corta. El párrafo largo solo va al log.
- `consulta_casas._aplicar_en_cotizacion` copia `resultado.motivo_seleccion` («Única casa con stock disponible (tienda)») a `motivo_seleccion` y a `comentario`. La tarea llama a la consulta automática después de guardar.
- `_tienda_por_dominio` title-casea el dominio: comercialramirezspa.cl queda «Comercialramirezspa».
- El serializer y la vista pública leen el JSON guardado. Una cotización vieja sigue mostrando la nota larga.

## Qué cambia

- `nombre_tienda_visible` agrega Comercial Ramírez y TodoAuto al canon que ya tiene Mundo Repuestos y Sergio Escobar.
- La línea con casa guarda ese nombre en `casa_repuesto_nombre` y la frase corta en `motivo_seleccion`. `proveedor_nombre` de una ficha web no se reescribe: lo usan las comparaciones de la ficha.
- `sanear_notas_linea` recorre la línea. Si un texto visible trae una frase prohibida, un motivo del selector o más de 160 caracteres siendo nota, lo reemplaza. No toca nombre, URL ni la descripción de la pieza.
- Se llama al final de `buscar_precios_web_cotizacion_task` (después de la consulta de casas), en el serializer del taller y en los repuestos públicos.
- Una especificación que ya es nota corta no vuelve a entrar como texto de búsqueda.
