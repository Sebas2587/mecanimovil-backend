## Context

`transaction_amount_refunded` acumula devoluciones. Mercado Pago no lo reemplaza por el contracargo, así que un `charged_back` puede llegar con el 30 ya reembolsado.

## Decisions

1. Si el estado o la evidencia durable dicen contracargo, el objetivo es la entrada completa.
2. El incremento sigue siendo objetivo menos lo ya reversado.
3. La marca queda en `Pago.metadata` y no se apaga con un webhook de reembolso más chico.

## Migration Plan

No hay migración.
