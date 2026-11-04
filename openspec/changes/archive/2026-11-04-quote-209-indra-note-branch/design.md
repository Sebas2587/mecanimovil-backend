## Context

`nota_especialista` ya no arma «tiene todos los repuestos. Precio a consultar.». Esa frase sigue visible porque `sanear_notas_linea` la trata como nota corta de mecánico (`tiene todos los repuestos`, `especialista `, `precio a consultar`) y no la vuelve a escribir. La tarea `buscar_precios_web_cotizacion_task` guarda después de ese saneo, y el serializer de lectura pasa por el mismo saneo. La marca queda en mayúsculas porque esa frase vieja interpolaba `vehiculo_marca` crudo.

`sucursal_para` recorre las sucursales y, en cada coincidencia de comuna «santiago», pisa la anterior. Lira 664 y Avenida Brasil 28 comparten comuna; queda la última, Brasil. El texto de match sale de `TallerDireccion` (calle, número, comuna, ciudad, detalles) y de `Usuario.direccion`. No lee `DireccionUsuario`. Una oficina virtual en Providencia cuyo texto dice Santiago, sin «La Florida» en esos campos, cae en Brasil. La base de producción no está accesible desde este entorno (Render MCP en error, sin `RENDER_API_KEY`; `DATABASE_URL` local es la base de test).

## Goals / Non-Goals

**Goals:**

- Reescribir la frase vieja, en la tarea y al leer, a la consulta con la referencia de esa línea y la marca en título.
- Conservar «tiene todos los repuestos de esta cotización» cuando el stock sí está verificado.
- La primera sucursal de Santiago cuando el texto solo nombra Santiago. Una comuna específica, también en `DireccionUsuario`, gana a Santiago.
- Un test que ejecuta `buscar_precios_web_cotizacion_task`.

**Non-Goals:**

- Hardcodear John Kennedy, La Florida o Vicuña Mackenna como sucursal del taller Mecanimovil.
- Geocodificar distancia.
- Cambiar los montos de mano de obra.

## Decisions

1. `sanear_notas_linea` rehace la nota si el texto afirma «tiene todos» sin «de esta cotización», o si dice «precio a consultar» con «especialista» y no es la frase de consulta actual. La referencia sale de `referencia_tienda` y `precio_referencia_clp`; si faltan, del `proveedor_nombre` cuando no es la casa especialista y hay precio unitario. Sin tienda validada no se agrega «Referencia».
2. En `sucursal_para`, la primera sucursal de comuna Santiago se conserva. Las comunas más específicas siguen primero.
3. `_lugar_del_taller` suma `DireccionUsuario.direccion` y `detalles`. Así una oficina virtual en `Usuario.direccion` no esconde el taller si está guardado como otra dirección del mismo usuario. La ciudad «Santiago» sigue en el texto; no alcanza para elegir Brasil porque Santiago ya no pisa la primera sucursal, y una comuna específica presente en el texto gana.

## Risks / Trade-offs

- Si ninguna dirección guardada nombra La Florida, el PDF queda en Lira 664 (primera sucursal que no es Concepción) hasta que el dueño complete `TallerDireccion.comuna`. No se inventa la comuna.
