## Why

El taller no tiene una caja que sume dinero realmente recibido. Los estados de avance y los flags de pago se confunden con cobro, el libro de Mercado Pago no se proyecta sin borrarlo, y el total de una cotización en la lista puede diferir del total que arma el editor con las mismas líneas.

## What Changes

- Libro append-only `CobroTaller` por taller, anclado a cita, solicitud u oferta. Abonos y reembolsos entran por su fecha local `America/Santiago`. El exigible y el saldo no se mezclan con el bruto ni el neto del período.
- La caja vacía no borra evidencia previa: un flag o un pago Mercado Pago sin movimiento sigue visible como pagado según esa fuente, no suma, y no se reescribe con null ni se muestra como deuda nueva. Un reembolso o contracargo de Mercado Pago domina esos flags en la presentación.
- Alta manual idempotente y contabilización del webhook sin bloquear el pago real. Reversos auditables, topados por el original. Costos registrados y estimados separados; el precio de tienda no es costo real.
- Lista y detalle de cotización del taller calculan el total con las líneas, la mano de obra y el descuento de esa misma respuesta, sin escribir en GET. La vista pública no recibe costos ni márgenes.

## Capabilities

### New Capabilities

- `caja-taller`: caja por período, movimientos, costos, provenance de pago y totales de cotización alineados a la respuesta.

### Modified Capabilities

- `pagos-mercadopago`: el webhook y la verificación de un pago aprobado siguen confirmando el pago aunque la caja falle; un reintento no duplica el movimiento.

## Impact

- Modelos y migración aditiva en `ordenes`. Endpoints `GET/POST /api/ordenes/caja/`.
- Serializer de orden del proveedor, pipeline comercial y serializer de cotización del taller.
- `pagos.views` llama a la caja después de persistir `Pago`, dentro de un aislamiento de errores.
- Sin backfill, sin acceso a producción y sin cambios de la vista pública ni del PDF.
