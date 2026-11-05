## Context

El libro ya era append-only, pero el candado solo cubría movimientos existentes, el reembolso de Mercado Pago usaba el acumulado como si fuera un delta y la solicitud no veía los movimientos de su oferta.

## Goals / Non-Goals

- Goals: una sola cifra de saldo por caso, reembolsos que no exceden lo cobrado, y un fallo de caja que no pierde el pago.
- Non-Goals: backfill, rediseño del cotizador y cambios del checkout de Mercado Pago.

## Decisions

1. `AnclaCaja` es la fila que se bloquea antes de sumar. Se crea en la misma transacción del primer movimiento.
2. El reembolso acumulado persiste en `Pago.metadata.transaction_amount_refunded` y la fila guarda solo el incremento.
3. La ancla canónica de una solicitud con oferta del mismo taller es la oferta. Citas y adicionales no se fusionan.
4. `margen_real_clp` es neto confirmado menos costo registrado. `margen_contratado_clp` queda separado.
5. Una transición que bajaría un `confirmado` se audita y no se aplica.
6. Si las líneas aceptadas no coinciden con el total guardado, el exigible es desconocido. El GET no congela nada.

## Risks / Trade-offs

- Un worker que arranque antes de `0051` falla la contabilización y la aísla. El `Pago` queda, con el acumulado ya guardado en su metadata, y el webhook siguiente reconstruye la caja.
- `obligacion_congelada_clp` solo existe si un guardado anterior la escribió. Este cambio no engancha todos los flujos de aceptación.

## Migration Plan

Aplicar `0050` y después `0051`. Reversa: bajar `0051` elimina solo `ordenes_anclacaja`.

## Open Questions

- Ninguna para este cierre.
