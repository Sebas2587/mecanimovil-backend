## Why

En un Fiat Bravo T-Jet la ficha de bujías Champion en Entretuercas cuesta $15.826 el pack x4, pero el costo se tomó por unidad y el margen dio −300 %. La misma línea no mostró el enlace ni la casa sugerida. El cotizador devuelve la cotización sin revisar si la unidad, el auto y el costo calzan.

## What Changes

- Antes de devolver la cotización del taller, cada repuesto pasa una validación: unidad de la ficha (pack, juego, kit, set, bidón), compatibilidad con el auto, y coherencia entre costo y precio cobrado.
- Si la ficha no es de este auto, no se cita y la línea queda `sin_referencia_valida`. Si el precio no se puede corregir, queda `requiere_revision` con un motivo. Si no hay ficha, el precio asumido dice por qué.
- La casa sugerida se llena también cuando la línea no trae casa. Un precio de ficha real reemplaza al asumido.
- Esas alertas no salen en la vista pública del cliente.

## Capabilities

### New Capabilities

### Modified Capabilities

- `orden-compra-repuestos`: la respuesta del taller incluye el estado de validación de cada repuesto y corrige el precio por unidad.

## Impact

- Código: nueva etapa al armar `CotizacionCanalSerializer` y el PDF de compra. Sin migración y sin llamada a un modelo externo: las reglas ya usadas para aceptar una ficha deciden.

## Non-goals

- No inventar una tabla de precios por pieza.
- No volver a buscar en la web al leer la cotización. Si hay varias fichas guardadas, se elige la que sí calza.
