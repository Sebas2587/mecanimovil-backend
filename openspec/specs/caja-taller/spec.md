# caja-taller Specification

## Purpose
Libro de caja del taller: movimientos confirmados, saldo y exigible separados, y costos registrados distintos del precio de tienda. Un libro vacío no borra la evidencia de pago ya guardada.

## Requirements

### Requirement: Caja por período suma movimientos confirmados

El sistema MUST exponer `GET /api/ordenes/caja/` para el taller del contexto autenticado. El período usa fechas locales `America/Santiago`, incluye ambos extremos y MUST rechazar un rango mayor a 366 días. El resumen MUST separar cobros brutos, reembolsos y neto. El neto MUST ser brutos menos reembolsos de movimientos `confirmado` con `contabiliza_clp` en ese período. Un movimiento `pendiente`, `rechazado` o `cancelado` MUST quedar fuera del neto. La serie MUST cubrir todo el período y la suma de su neto MUST igualar el neto del resumen. El detalle de movimientos MUST estar paginado y, sumando todas las páginas, MUST reconstruir el resumen.

#### Scenario: Abono y devolución en días distintos

- GIVEN un caso con exigible conocido 100
- WHEN se confirma un abono de 30 un día y un reembolso de 10 al día siguiente
- THEN el día del abono tiene bruto 30 y neto 30
- AND el día del reembolso tiene bruto 0, reembolsos 10 y neto -10
- AND el período completo tiene neto 20 y saldo 80
- AND el 100 no aparece en bruto ni en neto

#### Scenario: Rango mayor a 366 días

- GIVEN un usuario del taller
- WHEN pide un período de 367 días
- THEN la respuesta es 400 y no hay movimientos nuevos

### Requirement: Libro vacío conserva la evidencia legacy

Un flag `pagado`, una anotación o un `Pago` sin fila en `CobroTaller` MUST seguir visible. El sistema MUST NOT insertar un movimiento por aceptar, ejecutar o completar un trabajo, ni por un flag sin monto y fecha. Esos casos MUST NOT presentarse como deuda nueva ni reemplazar el flag guardado por null. `estado_cobro_ui` MUST usar `pagado_segun_oferta`, `pagado_segun_mp` o `pagado_segun_anotacion` cuando esa sea la evidencia, y `pago_sin_informacion` cuando no hay evidencia suficiente. `pago_sin_informacion` MUST NOT implicar pendiente ni cero. Sin movimiento, `neto_acumulado_clp` y `saldo_clp` MUST ser null.

#### Scenario: Flag de oferta sin movimiento

- GIVEN una oferta con `estado_pago_servicio=pagado` y ninguna fila de caja
- WHEN el taller lee la orden o el pipeline
- THEN `estado_pago_servicio` sigue `pagado`
- AND `estado_cobro_ui` es `pagado_segun_oferta`
- AND `pago_contabilizable` es falso
- AND el saldo no es el total del trabajo

#### Scenario: Reembolso de Mercado Pago domina el flag

- GIVEN una oferta marcada `pagado` y un `Pago` en `refunded` o `charged_back`
- WHEN se proyecta el cobro
- THEN `estado_cobro_ui` es `reembolsado`
- AND el flag almacenado sigue `pagado`

### Requirement: Idempotencia, reversos y permisos

Un POST manual MUST exigir `Idempotency-Key`. La misma clave y el mismo cuerpo MUST devolver el mismo movimiento. La misma clave con otro cuerpo MUST responder 409. Un reverso MUST ser otra fila, MUST NOT borrar la entrada y MUST NOT superar el monto original. Un POST manual MUST NOT modificar una fila `mercadopago`. Solo el mandante o el supervisor del taller dueño de la ancla pueden escribir. Otro taller MUST recibir 404. El mecánico MUST poder leer solo anclas asignadas y la respuesta MUST NOT incluir claves de costo ni margen. Un sobrepago sin confirmación explícita MUST rechazarse. Si el exigible es desconocido, el saldo MUST ser null y el abono MAY registrarse.

#### Scenario: Reintento idéntico y cuerpo distinto

- GIVEN un cobro manual ya creado con una clave
- WHEN la misma clave se repite con el mismo cuerpo
- THEN existe una sola fila
- WHEN la misma clave llega con otro monto
- THEN la respuesta es 409 y la fila original no cambia

#### Scenario: Mecánico y taller ajeno

- GIVEN un movimiento con costo registrado
- WHEN lo lee el mecánico asignado
- THEN la respuesta no contiene claves de costo ni margen
- WHEN lo pide un usuario de otro taller
- THEN la respuesta es 404

### Requirement: Mercado Pago no queda bloqueado por la caja

Al persistir un `Pago` de oferta, el sistema MUST intentar una fila idempotente. Si la caja falla, el pago y la respuesta del webhook MUST conservarse. Solo CLP entero suma. Otra moneda MUST guardarse con `contabiliza_clp=false` y quedar fuera del neto. El sistema MUST NOT contabilizar un pago solo porque el estado de la oferta pasó a `pagada`.

#### Scenario: Fallo de caja después de guardar el pago

- GIVEN un pago de oferta ya persistido
- WHEN la contabilización lanza un error
- THEN el `Pago` sigue existiendo
- AND el error no se propaga al webhook

### Requirement: Adicionales no se cuentan dos veces

El exigible de una cita MUST sumar una vez la cotización aceptada de origen y cada adicional aceptado con `ejecucion_adicional=misma_visita`. Un adicional `nueva_fecha` MUST ser exigible solo de la cita hija.

#### Scenario: Misma visita y nueva fecha

- GIVEN una cita con exigible 100, un adicional de la misma visita por 40 y uno de nueva fecha por 70
- WHEN se calcula el exigible
- THEN la cita padre exige 140
- AND la cita hija exige 70

### Requirement: Costo registrado distinto del precio de tienda

El precio verificado, de referencia o de marketplace MUST ser costo estimado. El precio cobrado MUST NOT usarse como costo. `margen_real_clp` MUST ser null si no hay costo registrado o no hay neto confirmado. Cuando ambos existen, `margen_real_clp` MUST ser el neto confirmado menos el costo registrado, y MUST NOT usar el exigible. `margen_contratado_clp` MUST nombrar aparte el exigible menos el costo registrado. `POST /api/ordenes/caja/costos/` MUST persistir el costo del caso para mandante o supervisor y MUST conservar el valor anterior como no vigente.

#### Scenario: Línea sin costo registrado

- GIVEN una línea con precio cobrado y sin `costo_registrado_clp`
- WHEN se calcula la economía de la respuesta
- THEN `margen_real_clp` es null
- AND el precio cobrado no se copia al costo

### Requirement: Totales de la misma respuesta sin escritura

La lista y el detalle de cotización del taller MUST calcular `total_clp` con las líneas ya validadas de esa respuesta, la suma de `mano_obra_lineas` y el descuento de `calcular_descuento_aplicado` sobre bruto con IVA incluido. `total_persistido_clp` MUST conservar el valor guardado. El GET MUST NOT guardar la cotización. Si falta el precio de una línea, `total_clp` MUST ser null y `totales_faltantes` MUST nombrar la línea. La vista pública MUST NOT incluir costo ni margen.

#### Scenario: GET no escribe

- GIVEN una cotización guardada
- WHEN el taller pide el detalle
- THEN `total_clp` de la respuesta coincide con la suma de las líneas devueltas, la mano de obra y el descuento
- AND el `total_clp` persistido no cambia

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
