# Delta: asistente-diagnostico

## ADDED Requirements

### Requirement: Generar guía de reparación con IA
El endpoint `POST /api/ordenes/proveedor-ordenes/{id}/asistente-ia/` **SHALL** generar una guía de reparación usando datos del vehículo y problema/servicio de la orden, con causas probables, procedimiento paso a paso y referencia de manual.

#### Scenario: Generar guía para mecánico asignado
- GIVEN un mecánico autenticado asignado a la orden
- WHEN hace POST a `/ordenes/proveedor-ordenes/{id}/asistente-ia/`
- THEN recibe HTTP 200 con `contenido` JSON estructurado y `disponible=true`

#### Scenario: IA deshabilitada
- GIVEN `ASISTENTE_DIAGNOSTICO_IA_ENABLED=false`
- WHEN se invoca POST asistente-ia
- THEN recibe HTTP 200 con `disponible=false` y mensaje explicativo

### Requirement: Permisos del asistente IA
Solo el taller, supervisor o el mecánico asignado a la orden **SHALL** acceder al asistente.

#### Scenario: Mecánico no asignado
- GIVEN un mecánico autenticado sin asignación en la orden
- WHEN intenta POST asistente-ia
- THEN recibe HTTP 403
