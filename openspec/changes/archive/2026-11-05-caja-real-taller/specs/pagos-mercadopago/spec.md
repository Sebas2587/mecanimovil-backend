## ADDED Requirements

### Requirement: Contabilizar un pago de oferta no bloquea Mercado Pago

Después de guardar un `Pago` vinculado a una oferta, el webhook y la verificación directa MUST intentar registrar el movimiento de caja del taller. Un error de esa contabilización MUST quedar aislado: el `Pago` permanece y la respuesta HTTP del flujo de pago MUST ser la de Mercado Pago, no la de la caja. Reintentar el mismo `payment_id_mp` MUST NOT crear una segunda entrada.

#### Scenario: Reintento del mismo pago

- GIVEN un `Pago` de oferta ya contabilizado como entrada
- WHEN el webhook reintenta el mismo `payment_id_mp` y el mismo estado
- THEN sigue existiendo una sola entrada para esa referencia

#### Scenario: La caja falla

- GIVEN un `Pago` de oferta recién guardado
- WHEN la contabilización de caja lanza una excepción
- THEN el `Pago` no se revierte
- AND la excepción no cambia la respuesta de éxito del pago
