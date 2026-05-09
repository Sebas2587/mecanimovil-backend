# checklists Spec Delta — Firma diferida del cliente

## ADDED Requirements

### Requirement: Firma diferida del cliente

`ChecklistInstance` **SHALL** soportar el estado intermedio
`PENDIENTE_FIRMA_CLIENTE` para representar el momento entre que el técnico
firma el cierre y el cliente lo confirma desde su app. La firma del cliente
**SHALL** poder enviarse desde una sesión autenticada distinta a la del
proveedor.

#### Scenario: Técnico firma sin cliente presente

- GIVEN un `ChecklistInstance` en estado `EN_PROGRESO` cuya orden está en
  `checklist_en_progreso`
- WHEN el proveedor hace `POST /api/checklists/instances/{id}/finalize/`
  con `firma_tecnico` (no envía `firma_cliente`)
- THEN la respuesta es 200 con `requiere_firma_cliente=true`
- AND `instance.estado == 'PENDIENTE_FIRMA_CLIENTE'`
- AND `instance.firma_tecnico` queda persistida
- AND `instance.firma_cliente` permanece `null`
- AND `instance.fecha_finalizacion` permanece `null`
- AND `orden.estado == 'pendiente_firma_cliente'`

#### Scenario: Compatibilidad con técnicos en versión vieja

- GIVEN un `ChecklistInstance` en `EN_PROGRESO`
- WHEN el proveedor envía `firma_tecnico` y `firma_cliente` en la misma
  petición a `finalize`
- THEN la respuesta es 200 con `requiere_firma_cliente=false`
- AND `instance.estado == 'COMPLETADO'`
- AND `orden.estado == 'completado'`

### Requirement: Endpoint firmar-cliente

El backend **SHALL** exponer
`POST /api/checklists/instances/{id}/firmar-cliente/` con
`permission_classes=[IsAuthenticated]`. El endpoint **SHALL** validar que
`request.user` sea el cliente dueño de la orden asociada y que la
instancia esté en `PENDIENTE_FIRMA_CLIENTE`.

#### Scenario: Cliente dueño firma desde su app

- GIVEN un `ChecklistInstance` en `PENDIENTE_FIRMA_CLIENTE` cuya orden
  pertenece al usuario autenticado
- WHEN el usuario hace
  `POST /api/checklists/instances/{id}/firmar-cliente/` con
  `firma_cliente` (Base64) y opcional `ubicacion_lat` / `ubicacion_lng`
- THEN la respuesta es 200 con `estado='COMPLETADO'`
- AND `instance.firma_cliente` queda persistida
- AND `instance.fecha_finalizacion` queda con `timezone.now()`
- AND `orden.estado == 'completado'`
- AND el signal `post_save(ChecklistInstance)` dispara
  `actualizar_salud_desde_checklist`

#### Scenario: Usuario distinto al cliente recibe 403

- GIVEN un `ChecklistInstance` en `PENDIENTE_FIRMA_CLIENTE`
- WHEN un usuario autenticado distinto al cliente dueño llama al
  endpoint
- THEN la respuesta es 403 con un mensaje `No tienes permiso para firmar`

#### Scenario: Estado inválido bloquea la firma

- GIVEN un `ChecklistInstance` en `EN_PROGRESO` o `COMPLETADO`
- WHEN el cliente dueño llama al endpoint
- THEN la respuesta es 400 con detalle del estado actual
- AND no se modifica `firma_cliente`

### Requirement: Lectura del cliente con firma pendiente

`GET /api/checklists/instances/by_order/{orden_id}/` **SHALL** permitir
al cliente dueño acceder al checklist cuando la instancia está en
`PENDIENTE_FIRMA_CLIENTE`, no solo cuando está `COMPLETADO`. El payload
**SHALL** indicar `requiere_firma_cliente` para que la app pueda
mostrar la tarjeta de firma.

#### Scenario: Cliente revisa checklist mientras firma pendiente

- GIVEN un `ChecklistInstance` en `PENDIENTE_FIRMA_CLIENTE`
- WHEN el cliente dueño hace `GET .../by_order/{orden_id}/`
- THEN la respuesta es 200 con datos del checklist y
  `requiere_firma_cliente=true`

### Requirement: Notificación al cliente cuando técnico firma

El backend **SHALL** enviar un push y crear una `Notificacion` in-app al
cliente dueño cuando un `ChecklistInstance` transiciona a
`PENDIENTE_FIRMA_CLIENTE`, usando el tipo `servicio_pendiente_firma` con
deeplink al detalle de la solicitud.

#### Scenario: Push enviado al cliente al pasar a pendiente firma

- GIVEN un proveedor que ejecuta `finalize` con solo `firma_tecnico`
- WHEN la transacción se commitea
- THEN se encola `send_expo_push_notification` para el usuario dueño
  con title "Tu servicio espera tu firma"
- AND se crea una `Notificacion` con `dedup_key` por `orden_id`
