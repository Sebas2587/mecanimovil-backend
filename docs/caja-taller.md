# Caja del taller

Contrato para el frontend. La caja nueva empieza vacía. Eso no borra ni convierte en deuda lo que ya estaba marcado como pagado.

## Qué suma y qué no

`GET /api/ordenes/caja/?desde=YYYY-MM-DD&hasta=YYYY-MM-DD&granularidad=dia|semana|mes`

Fechas inclusive, zona `America/Santiago`. Máximo 366 días. `page` y `casos_page` parten en 1. `page_size` máximo 100.

| Campo | Significado |
|---|---|
| `resumen.cobros_brutos_clp` | Entradas confirmadas en CLP del período |
| `resumen.reembolsos_clp` | Reembolsos y contracargos confirmados |
| `resumen.neto_clp` | Bruto menos reembolsos. No incluye el total del trabajo |
| `resumen.pendientes_no_sumados_clp` | Movimientos aún no confirmados. No es “desconocido” |
| `resumen.completo` | Falso si hay legacy o moneda distinta de CLP fuera de la suma |
| `resumen.conocido_parcial` | La suma es solo el libro. No es el total del negocio |
| `resumen.faltantes` | `legacy_sin_movimiento`, `moneda_no_clp` |
| `serie` | Un bucket por día, semana (lunes) o mes. La suma de `neto_clp` reconstruye el resumen |
| `movimientos` | Página. Sumar todas las páginas reconstruye el resumen |
| `casos` | Exigible, neto acumulado y saldo del caso, no del día |

Cada fila de `movimientos.results` y de `casos.results` trae `cliente_nombre`, `vehiculo_patente` y `folio`. Son el dato ya guardado de una ancla de este taller: el detalle de la cita, y si falta, la cotización del mismo taller; en una orden, el cliente y la patente; en una oferta, la orden del taller o, si no hay, la solicitud de esa oferta. Un texto vacío queda null. No se inventa el nombre "Cliente" ni un folio. Un GET no asigna `numero_publico`. El mecánico los ve solo en anclas que ya puede leer. No vienen teléfono, correo ni dirección. Una ancla de otro taller no aporta esos datos.

Ejemplo sintético, exigible 100: abono 30 un día y devolución 10 al día siguiente. El 100 no entra a la caja. Neto del período 20. Saldo del caso 80. La entrada de 30 permanece; la devolución es otra fila.

`saldo_clp` null y `saldo_conocido` false significan que no hay obligación conocida o que el caso solo tiene evidencia vieja. No es saldo 0 y no es deuda nueva.

## Evidencia vieja y estado para la UI

Orden y pipeline agregan, sin borrar los flags:

- `estado_pago_repuestos` y `estado_pago_servicio` se copian de la oferta cuando existe. Si no hay oferta, las claves no vienen. Un flag `pagado` no se reemplaza por null.
- `estado_cobro_ui` es la etiqueta nueva.
- `pago_contabilizable` es true solo si hay un movimiento confirmado con monto.
- `pago_provenance` trae `dominio`, flags, estado Mercado Pago, anotación, neto y saldo.

| `estado_cobro_ui` | Lectura en la UI de etapa 1 |
|---|---|
| `pagado`, `pagado_segun_oferta`, `pagado_segun_mp`, `pagado_segun_anotacion` | Pagado. Si `pago_contabilizable` es false, no entra a la caja |
| `parcial`, `por_cobrar` | Por cobrar, con `saldo_clp` cuando `saldo_conocido` |
| `reembolsado` | Mercado Pago o un reverso del libro dominan un flag viejo que siga diciendo pagado |
| `pago_sin_informacion` | Pago sin información. No es pendiente y no es cero |

Aceptar, ejecutar o completar un trabajo no crea un cobro.

## Escritura

`POST /api/ordenes/caja/cobros/` con header `Idempotency-Key`.

```json
{
  "ancla_tipo": "cita",
  "ancla_id": "15",
  "tipo": "entrada",
  "componente": "total",
  "monto_clp": 30,
  "fecha_efectiva": "2026-03-02",
  "movimiento_origen_id": null,
  "motivo": "",
  "confirmar_sobrepago": false
}
```

`ancla_tipo` de entrada es `cita`, `solicitud` u `oferta`. Si la solicitud tiene oferta del mismo taller, el movimiento se guarda en la oferta: la respuesta trae `ancla_tipo=oferta` y el `ancla_id` de esa oferta. Cita, adicional `misma_visita` y cita hija `nueva_fecha` no se mezclan con la oferta ni entre sí. Un reverso de otra ancla responde 409 `reverso_ancla_distinta`.

`fecha_efectiva` es un día real. `2026-02-30` responde 400 `fecha_invalida` y no crea fila. El monto es CLP entero. La misma clave y el mismo cuerpo devuelven la misma fila. Otro cuerpo con la misma clave responde 409 `idempotencia_conflicto`. Dos claves distintas del mismo caso se serializan sobre una fila de ancla, también si el libro estaba vacío: la segunda no pasa el saldo. Un reembolso manual apunta a `movimiento_origen_id`, no borra la entrada y no puede superar su monto (`reverso_excede_original`), aunque lleguen juntos. Un reembolso de Mercado Pago no se carga a mano (`reverso_mp_solo_webhook`). Sin `confirmar_sobrepago`, un abono sobre el exigible responde 409 `sobrepago`.

Una fila `pendiente`, `rechazada`, `cancelada` o en otra moneda no abre el libro. El flag pagado sigue siendo `pagado_segun_oferta` (o la fuente que corresponda), el saldo queda null y `aviso_libro` es `sin_efecto_contable`. `pendientes_no_sumados_clp` informa ese monto sin tratarlo como deuda. Un webhook que pide bajar una entrada ya `confirmado` a `pending` o `in_mediation` no la saca de la caja: queda en `metadata.eventos_ignorados`. El reembolso es otra fila.

`transaction_amount_refunded` de Mercado Pago es el acumulado de devoluciones, no el contracargo. La caja guarda solo el incremento. 10, luego 30, luego 100 dejan reembolsos que suman 100, nunca 140. Un 10 que llega después de un 30 no resta. El acumulado se persiste en `Pago.metadata` antes de contabilizar. Si la caja falla, el reintento reconstruye ese parcial sin el cuerpo del webhook.

Un pago en `charged_back` cierra la entrada completa. Si ya había una devolución de 30 sobre 100, el contracargo agrega 70 y el neto queda 0. No se vuelve a restar esos 30. La marca `contracargo_observado` queda en el `Pago` antes de contabilizar y no la borra un webhook de reembolso posterior, aunque traiga un acumulado menor. Repetir el contracargo no crea otra fila. Ese dato es interno del pago: la caja lo muestra como movimiento `contracargo`, sin un campo nuevo en la respuesta.

`POST /api/ordenes/caja/costos/` guarda `tipo` `registrado` o `estimado` para `repuestos` o `servicio`. El precio de tienda no es costo real.

En el caso, para mandante y supervisor:

| Campo | Significado |
|---|---|
| `margen_real_clp` y `resultado_caja_clp` | Neto confirmado menos costo registrado. Con obligación 100, cobro 30, reembolso 10 y costo 40, el valor es -20 |
| `margen_contratado_clp` | Exigible menos costo registrado. En el ejemplo, 60. No es caja |
| `margen_estimado_clp` | Exigible menos costo estimado. No es caja |
| `margen_faltantes` | `costo_registrado`, `neto_no_confirmado` o `exigible_desconocido` cuando el número no se puede cerrar |

Sin costo registrado o sin neto confirmado, `margen_real_clp` es null.

Mandante y supervisor escriben y ven costos. El mecánico lee solo sus anclas y la respuesta no trae claves de costo ni margen. Un caso de otro taller responde 404.

## Totales de cotización del taller

En lista y detalle, `total_clp` sale de las líneas de esa misma respuesta: precio unitario por cantidad, más la suma de `mano_obra_lineas`, menos el descuento. Los precios ya incluyen IVA. `total_persistido_clp` es el número guardado. `total_alineado` dice si coinciden. Si falta un precio, `total_clp` es null, `totales_completos` es false y `totales_faltantes` nombra la línea. Ese null no es $0. `total_conocido_parcial_clp` es la parte que sí se pudo sumar. Leer la cotización no la guarda.

La obligación de caja de una cita usa esa misma cuenta, no un total viejo distinto:

| `obligacion_fuente` | Lectura |
|---|---|
| `lineas_respuesta` | Aceptada y alineada. `obligacion_clp` es el `total_clp` de la respuesta |
| `congelada` | Había `metadata.obligacion_congelada_clp` escrito en un guardado previo. Un GET no la crea ni la cambia |
| `discrepancia` | Aceptada, pero el total guardado no coincide con las líneas. `obligacion_clp` es null. El saldo de caja queda desconocido: no se cobra contra el número viejo ni contra el nuevo |
| `incompleto` | Falta precio de una línea |
| `no_aceptada` | La cotización todavía no es obligación |
| `oferta_aceptada` | El caso canónico es una oferta y el exigible es `precio_total_ofrecido` |

El caso de caja repite `exigible_fuente` y `exigible_faltantes`.

La vista pública y el PDF no reciben costo ni margen.
