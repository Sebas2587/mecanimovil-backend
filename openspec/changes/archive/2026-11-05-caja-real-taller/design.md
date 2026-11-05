## Context

`Pago` es el registro de Mercado Pago. `OfertaProveedor.estado_pago_*` y `cobro_*` de orden y cita son anotaciones. `ganancias-resumen` trata un trabajo terminado como ingreso y no es la caja. La respuesta de cotización del taller ya valida líneas en lectura y deja `total_clp` persistido.

## Goals / Non-Goals

**Goals:**

- Sumar solo movimientos confirmados en CLP entero, por fecha local.
- Separar exigible, saldo, bruto, reembolsos y neto.
- Conservar la evidencia legacy en campos adicionales, sin inserts automáticos.
- Idempotencia, reversos que no borran la entrada, y permisos de taller.
- Igualar el total de lista y detalle a las líneas de esa respuesta.

**Non-Goals:**

- Backfill, comandos que inventen cobros, o reemplazar `Pago`.
- Cambiar el PDF, los verificadores de pack/litros/compatibilidad, o el serializer público.
- Enviar correo, webhooks salientes o llamar a Mercado Pago desde la caja.

## Decisions

1. **Un movimiento, una fila.** `CobroTaller` es append-only. La unicidad `(taller, origen, ref_externa)` cubre el webhook (`mp:{payment_id}`) y el POST manual (`manual:{Idempotency-Key}`). Un reembolso es otra fila (`mp-refund:{payment_id}:{monto}`) que apunta a la entrada. La suma de reversos confirmados no puede pasar el monto de la entrada.
2. **La fecha de caja es `fecha_local`.** Una fecha sin hora se guarda a las 12:00 de `America/Santiago` para no caer en el hueco de horario de verano. El período incluye ambos extremos y rechaza más de 366 días. La serie vacía también se emite, así la suma de la serie reconstruye el resumen.
3. **Legacy fuera del libro.** La proyección lee flags, anotaciones y `Pago` en lectura. `estado_cobro_ui` distingue `pagado_segun_oferta`, `pagado_segun_mp`, `pagado_segun_anotacion`, `pagado`, `parcial`, `por_cobrar`, `reembolsado` y `pago_sin_informacion`. `unknown` no se traduce a pendiente ni a 0. Si no hay movimiento, `neto_acumulado_clp` y `saldo_clp` van null. Un flag `pagado` no se pisa.
4. **Mercado Pago manda en un reverso.** `refunded` o `charged_back` fijan `estado_cobro_ui=reembolsado` aunque el flag siga en `pagado`. El flag almacenado no se modifica.
5. **El webhook no depende de la caja.** `intentar_contabilizar_pago_mp` traga cualquier error después de que `Pago` ya se guardó. Moneda distinta de CLP queda registrada con `contabiliza_clp=false` y fuera del neto.
6. **Costo real es el registrado.** `precio_verificado_clp`, `precio_referencia_clp` y `precio_marketplace_clp` alimentan costo estimado. El precio cobrado no rellena ni el estimado ni el real. Sin costo registrado, `margen_real_clp` es null. `CostoTaller` guarda el costo del caso y conserva la fila anterior como no vigente.
7. **Ancla.** Cita, solicitud u oferta del mismo taller. Un adicional `misma_visita` aceptado suma una vez al exigible de la cita padre. `nueva_fecha` es la cita hija y no se suma al padre. La cotización no es ancla.
8. **Permisos.** Mandante y supervisor leen y escriben, incluidos costos. El mecánico lee solo anclas asignadas y la respuesta no trae claves de costo ni margen. Otro taller recibe 404.
9. **Totales de cotización.** Después de validar las líneas, el total de la respuesta sale de esas líneas, de `mano_obra_lineas` y de `calcular_descuento_aplicado` (IVA incluido, sin segundo IVA). `total_persistido_clp` conserva el guardado. El GET no llama a `save`.

## Risks / Trade-offs

- Un pago histórico con monto y fecha sigue fuera del neto hasta que un webhook nuevo lo contabilice. La UI lo muestra como pagado según Mercado Pago, no como deuda. → Documentado para el frontend.
- Cambiar `total_clp` de la respuesta del taller cuando las líneas validadas no coinciden con lo persistido. → `total_persistido_clp` deja el número anterior visible. La vista pública no cambia.
- Un costo estimado deja de presentarse como margen real. → `margen_clp` sigue la base estimada cuando existe referencia, y `margen_real_clp` queda null sin registro.

## Migration Plan

1. Aplicar `ordenes.0050` (crea tablas, no inserta filas).
2. Desplegar el backend. Los GET existentes ganan campos. Los flags guardados no se reescriben.
3. El frontend pasa a leer `estado_cobro_ui` y `pago_provenance` sin tratar un libro vacío como deuda.
4. Reversa: migrar a `0049`. Las tablas nuevas se eliminan. `Pago` y los flags quedan igual.

## Open Questions

Ninguna. El contrato de la corrida anterior queda cerrado por estas decisiones.
