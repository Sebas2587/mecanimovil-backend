## ADDED Requirements

### REQ-IA-CITA-ENDPOINT

El endpoint `GET/POST /api/ordenes/citas-agenda-personal/{id}/asistente-ia/` **SHALL** generar o consultar guías de reparación IA para citas personales activas del proveedor.

#### Scenario: Mecánico asignado consulta caché vacía

- GIVEN un mecánico de equipo autenticado con cita personal activa asignada a su `MiembroTaller`
- WHEN hace GET a `/ordenes/citas-agenda-personal/{id}/asistente-ia/`
- THEN recibe HTTP 200 con `disponible=false` y `contenido=null` si no hay diagnóstico previo

#### Scenario: Mecánico sin acceso

- GIVEN un mecánico autenticado y una cita asignada a otro miembro
- WHEN intenta GET o POST asistente-ia
- THEN recibe HTTP 403 o 404 según scoping del queryset

#### Scenario: Feature flag deshabilitado

- GIVEN `ASISTENTE_DIAGNOSTICO_IA_ENABLED=false`
- WHEN hace POST asistente-ia
- THEN recibe HTTP 200 con `disponible=false` y mensaje de error descriptivo
