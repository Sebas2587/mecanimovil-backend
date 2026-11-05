## ADDED Requirements

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

El precio verificado, de referencia o de marketplace MUST ser costo estimado. El precio cobrado MUST NOT usarse como costo. `margen_real_clp` MUST ser null si no hay costo registrado. `POST /api/ordenes/caja/costos/` MUST persistir el costo del caso para mandante o supervisor y MUST conservar el valor anterior como no vigente.

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
