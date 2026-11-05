## Why

La revisión de la caja encontró nueve huecos donde dos operaciones concurrentes, un reembolso acumulado o un total desalineado podían contar dinero de más o presentar una deuda que no existe.

## What Changes

- Candado por fila de ancla, también con libro vacío.
- Reverso solo del mismo caso y bajo el mismo candado.
- Reembolso de Mercado Pago tratado como acumulado, con evidencia persistida antes de aislar un fallo.
- Solicitud y oferta del mismo taller comparten libro.
- Filas sin efecto contable no pisan un pago legacy.
- Margen real es neto cobrado menos costo registrado.
- Una entrada confirmada no baja de estado por un webhook atrasado.
- El exigible de la cita sale de la misma cuenta que la respuesta y queda desconocido si no está alineada.

## Capabilities

### New Capabilities

- Ninguna. Se ajusta `caja-taller`.

### Modified Capabilities

- `caja-taller`: integridad de saldo, reembolsos, ancla canónica y obligación.

## Impact

- Migración aditiva `0051_ancla_caja`. No se consulta al importar.
- API de lectura suma campos. `margen_real_clp` pasa a ser resultado de caja.
- Un POST contra una solicitud con oferta responde con ancla `oferta`.
