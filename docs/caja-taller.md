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

`ancla_tipo` es `cita`, `solicitud` u `oferta`. El monto es CLP entero. La misma clave y el mismo cuerpo devuelven la misma fila. Otro cuerpo con la misma clave responde 409 `idempotencia_conflicto`. Un reembolso manual apunta a `movimiento_origen_id`, no borra la entrada y no puede superar su monto (`reverso_excede_original`). Un reembolso de Mercado Pago no se carga a mano (`reverso_mp_solo_webhook`). Sin `confirmar_sobrepago`, un abono sobre el exigible responde 409 `sobrepago`.

`POST /api/ordenes/caja/costos/` guarda `tipo` `registrado` o `estimado` para `repuestos` o `servicio`. El precio de tienda no es costo real. Sin costo registrado, `margen_real_clp` es null.

Mandante y supervisor escriben y ven costos. El mecánico lee solo sus anclas y la respuesta no trae claves de costo ni margen. Un caso de otro taller responde 404.

## Totales de cotización del taller

En lista y detalle, `total_clp` sale de las líneas de esa misma respuesta: precio unitario por cantidad, más la suma de `mano_obra_lineas`, menos el descuento. Los precios ya incluyen IVA. `total_persistido_clp` es el número guardado. `total_alineado` dice si coinciden. Si falta un precio, `total_clp` es null, `totales_completos` es false y `totales_faltantes` nombra la línea. `total_conocido_parcial_clp` es la parte que sí se pudo sumar. Leer la cotización no la guarda.

La vista pública y el PDF no reciben costo ni margen.
