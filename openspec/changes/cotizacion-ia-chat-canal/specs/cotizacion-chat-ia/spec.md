# cotizacion-chat-ia

## ADDED Requirements

### REQ-COT-IA-GENERAR
POST `/ordenes/cotizaciones-canal/generar-ia/` SHALL crear borrador con servicio, repuestos, mano de obra y totales estimados.

#### Scenario: Generación exitosa
- GIVEN mandante autenticado con conversación omnicanal
- WHEN POST con vehículo y descripción del problema
- THEN respuesta incluye `cotizacion_id` y líneas editables

### REQ-COT-ENVIAR
POST `/ordenes/cotizaciones-canal/{id}/enviar/` SHALL enviar resumen al cliente y marcar estado `enviada`.

#### Scenario: WhatsApp interactive
- GIVEN cotización en borrador
- WHEN mandante envía
- THEN cliente recibe botones Aceptar/Rechazar en WhatsApp

### REQ-COT-ACEPTAR
Webhook interactive SHALL transicionar cotización a `aceptada` o `rechazada` de forma idempotente.

### REQ-COT-PLANTILLA
GET/POST `/ordenes/cotizaciones-canal/plantillas/` SHALL permitir guardar y reutilizar snapshots del taller.
