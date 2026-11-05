## Why

Un contracargo que llega con el acumulado de la devolución parcial todavía en 30 dejaba el neto en 70. El estado `charged_back` cierra la entrada completa.

## What Changes

- El objetivo de un `charged_back` es el monto de la entrada. El reembolso ya contabilizado no se duplica.
- `contracargo_observado` se guarda en el `Pago` antes de contabilizar y un reembolso posterior no lo borra.

## Capabilities

### New Capabilities

- Ninguna.

### Modified Capabilities

- `caja-taller`: reversa de contracargo después de un reembolso parcial.

## Impact

- Sin migración. Sin campo nuevo en la respuesta de caja. El movimiento sigue siendo `contracargo`.
