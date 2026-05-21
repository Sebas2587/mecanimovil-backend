# solicitud-activa

## Requirements

### REQ-ESTADOS-ACTIVOS-DUPLICADO
Una solicitud **SHALL** considerarse activa para bloqueo de duplicado si su `estado` está en: `creada`, `seleccionando_servicios`, `publicada`, `con_ofertas`, `pendiente_confirmacion`, `esperando_creditos_proveedor`, `adjudicada`, `pendiente_pago`, `pagada`, `en_ejecucion`.

### REQ-VERIFICAR-SERVICIO-ACTIVO
`GET /ordenes/solicitudes-publicas/verificar-servicio-activo/` con `vehiculo_id` y `servicio_ids` **SHALL** devolver `{ bloqueado, solicitud_id, servicios_en_conflicto, mensaje }` para el cliente autenticado.

### REQ-CREATE-DUPLICADO
`POST` crear solicitud **SHALL** usar la misma regla y devolver 400 en `servicios_solicitados` si hay conflicto.
