## MODIFIED Requirements

### Requirement: Reembolso de Mercado Pago acumulado

`transaction_amount_refunded` MUST tratarse como acumulado de devoluciones. La caja MUST registrar solo el incremento que falta. Un acumulado menor o repetido MUST NOT restar ni duplicar. Un `charged_back` MUST llevar la reversa acumulada al monto de la entrada, sin volver a sumar el reembolso ya contabilizado. La evidencia del acumulado y del contracargo MUST persistirse en el `Pago` antes de aislar un fallo de caja, sin datos del pagador. Un evento de reembolso posterior e inferior MUST NOT borrar esa evidencia ni resucitar saldo.

#### Scenario: 10, luego 30, luego 100

- GIVEN una entrada de 100
- WHEN llegan acumulados 10, 30 y 100, con reintento del 30
- THEN la suma de reembolsos es 100

#### Scenario: 30 y después 10

- GIVEN una entrada de 100
- WHEN llega el acumulado 30 y después el 10
- THEN la suma de reembolsos sigue en 30

#### Scenario: Reembolso parcial y luego contracargo

- GIVEN una entrada de 100 y un reembolso acumulado de 30 ya contabilizado
- WHEN el pago pasa a `charged_back` y `transaction_amount_refunded` sigue en 30
- THEN la reversa acumulada es 100 y el neto es 0
- AND repetir el contracargo no crea otra fila
- AND un reembolso posterior de 10 no resucita saldo ni supera la entrada
