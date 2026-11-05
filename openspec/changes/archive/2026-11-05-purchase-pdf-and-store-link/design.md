## Context

`generar_pdf_orden_compra` escribe párrafos con fpdf2. El taller, la fecha y las casas salen, pero no hay encabezado de identidad, ni tabla, ni número de página, ni enlace. La cotización del taller ya guarda `url_producto` y `precio_referencia_clp` en sitios distintos; la app no tiene un trío estable para «Ver en tienda». La vista pública usa una lista blanca y no debe ganar esos datos.

El logo del taller es `foto_perfil`. El RUT está en el taller. El correo está en el usuario. La dirección física está en `TallerDireccion`. Las casas especialistas no publican horario: solo se imprime si el perfil o la línea lo traen.

## Goals / Non-Goals

**Goals:**

- Un PDF que se pueda entregar en la casa: identidad, vehículo, una sección por casa, tabla y enlace.
- Tres campos siempre presentes en cada repuesto de la API del taller.
- Seguir sin mano de obra, sin total del cliente y sin citar una referencia que no pasó las compuertas.

**Non-Goals:**

- Horarios inventados.
- Cambiar el PDF público del cliente.
- Persistir una columna nueva en Postgres.

## Decisions

1. **Misma compuerta que el PDF actual.** `referencia_de_linea` usa `_referencia_consulta` cuando la línea está a consultar. Si la compuerta no devuelve tienda y monto, `url_referencia` queda vacío y `precio_verificado_clp` queda nulo. Una ficha es una URL http(s) con camino; la portada del sitio no cuenta.

2. **Los tres campos se arman al serializar.** `url_referencia` (string), `tienda_referencia` (string) y `precio_verificado_clp` (entero o null). El historial no es tienda: no llena el trío. El PDF usa la misma función para la columna Referencia y para el enlace «Ver ficha».

3. **El documento reutiliza la agrupación.** Casa, sucursal del taller y fusión de la misma dirección se mantienen. Encima se dibuja encabezado, ficha del vehículo, insignia de especialista, tabla y pie. El pie dice exactamente «No incluye mano de obra ni el valor cobrado al cliente.»

4. **Identidad solo con datos reales.** Logo si `foto_perfil` se puede leer. Si no, iniciales. Dirección, teléfono, RUT y correo solo cuando existen.

## Risks / Trade-offs

- [Una cotización vieja no tiene `url_referencia` guardado] → Se calcula al leer, desde `url_producto` o `fuentes_detalle`.
- [El unitario sin ficha es el precio del cliente] → No se publica como `precio_verificado_clp`. El PDF, si la línea no está a consultar y no hay ficha, sigue diciendo «Referencia» y no el total de la cotización.
- [fpdf2 y un logo ilegible] → Se omiten el logo y se usan las iniciales.

## Migration Plan

Sin migración. Deploy del servicio web. Rollback: revertir el commit.

## Open Questions

Ninguna.
