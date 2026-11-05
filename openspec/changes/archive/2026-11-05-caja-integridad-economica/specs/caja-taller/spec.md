## MODIFIED Requirements

### Requirement: Costo registrado distinto del precio de tienda

El precio verificado, de referencia o de marketplace MUST ser costo estimado. El precio cobrado MUST NOT usarse como costo. `margen_real_clp` MUST ser null si no hay costo registrado o no hay neto confirmado. Cuando ambos existen, `margen_real_clp` MUST ser el neto confirmado menos el costo registrado, y MUST NOT usar el exigible. `margen_contratado_clp` MUST nombrar aparte el exigible menos el costo registrado. `POST /api/ordenes/caja/costos/` MUST persistir el costo del caso para mandante o supervisor y MUST conservar el valor anterior como no vigente.

#### Scenario: Línea sin costo registrado

- GIVEN una línea con precio cobrado y sin `costo_registrado_clp`
- WHEN se calcula la economía de la respuesta
- THEN `margen_real_clp` es null
- AND el precio cobrado no se copia al costo

#### Scenario: Caja y obligación no se mezclan

- GIVEN obligación 100, cobro 30, reembolso 10 y costo registrado 40
- WHEN el mandante lee el caso
- THEN `margen_real_clp` es -20
- AND `margen_contratado_clp` es 60

## ADDED Requirements

### Requirement: El caso se serializa aunque el libro esté vacío

Dos cobros manuales de claves distintas sobre un caso sin movimientos MUST tomar una fila estable del caso antes de evaluar el saldo. La unicidad de `ref_externa` MUST NOT ser el único candado. Un reverso MUST ser del mismo caso canónico que la entrada y MUST contar los reversos ya confirmados bajo ese mismo candado.

#### Scenario: Dos primeros abonos concurrentes

- GIVEN un exigible de 100 y un libro vacío
- WHEN dos POST con claves distintas intentan abonar 80 cada uno
- THEN uno queda confirmado y el otro responde 409 `sobrepago`
- AND el neto no supera 100

#### Scenario: Reverso de otra ancla

- GIVEN una entrada del caso A
- WHEN se pide un reembolso citando el caso B
- THEN la respuesta es 409 `reverso_ancla_distinta`
- AND no se crea el reverso

### Requirement: Reembolso de Mercado Pago acumulado

`transaction_amount_refunded` MUST tratarse como acumulado. La caja MUST registrar solo el incremento que falta. Un acumulado menor o repetido MUST NOT restar ni duplicar. La evidencia del acumulado MUST persistirse en el `Pago` antes de aislar un fallo de caja, sin datos del pagador.

#### Scenario: 10, luego 30, luego 100

- GIVEN una entrada de 100
- WHEN llegan acumulados 10, 30 y 100, con reintento del 30
- THEN la suma de reembolsos es 100

#### Scenario: 30 y después 10

- GIVEN una entrada de 100
- WHEN llega el acumulado 30 y después el 10
- THEN la suma de reembolsos sigue en 30

### Requirement: Solicitud y oferta son un solo libro

Una solicitud con oferta del mismo taller MUST escribir, bloquear, sumar y proyectar sobre la oferta. Una cita, un adicional `misma_visita` y una cita `nueva_fecha` MUST NOT colisionar con ese libro ni entre sí.

#### Scenario: Abono por la solicitud visible en la oferta

- GIVEN una solicitud ligada a una oferta de exigible 100
- WHEN se registra un abono de 60 contra la solicitud
- THEN el movimiento queda en la oferta
- AND un segundo abono de 50 contra la oferta responde 409 `sobrepago`

### Requirement: Una fila sin efecto contable no inventa deuda

Una fila pendiente, rechazada, cancelada o en moneda distinta de CLP MUST NOT invalidar un flag o anotación pagada ni presentar saldo igual al exigible. La respuesta MUST informar esas filas sin sumarlas.

#### Scenario: Flag pagado y movimiento pendiente

- GIVEN una oferta marcada pagada y una fila pendiente de 100
- WHEN se proyecta el cobro
- THEN `estado_cobro_ui` sigue `pagado_segun_oferta`
- AND `saldo_clp` es null

### Requirement: Una entrada confirmada no se borra por un webhook atrasado

Un estado posterior `pending` o `in_mediation` MUST NOT cambiar una entrada `confirmado` ni excluirla del neto. El intento MUST quedar en `eventos_ignorados`. El reembolso MUST ser un movimiento explícito.

#### Scenario: Aprobado y después en mediación

- GIVEN una entrada confirmada de 100
- WHEN el mismo pago pasa a `in_mediation`
- THEN la entrada sigue `confirmado` y dentro del neto

### Requirement: La obligación usa la misma cuenta que la respuesta

Si la cotización aceptada está alineada, el exigible MUST ser el total de las líneas de esa respuesta. Si no está alineada, el exigible MUST ser desconocido y MUST NOT usar el total persistido ni el total recién calculado como deuda. Un GET MUST NOT escribir `obligacion_congelada_clp`. Si esa clave ya existe, MUST usarse como obligación congelada.

#### Scenario: Total guardado distinto de las líneas

- GIVEN una cotización aceptada con total guardado 100 y líneas que suman 70
- WHEN se lee la cotización y el exigible de la cita
- THEN `obligacion_fuente` es `discrepancia` y el exigible es null
- AND el total guardado no cambia
