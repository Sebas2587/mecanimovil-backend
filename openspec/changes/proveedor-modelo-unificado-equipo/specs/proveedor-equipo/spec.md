# Delta: proveedor-equipo

## ADDED Requirements

### REQ-MIEMBRO-TALLER
Un `Taller` **SHALL** poder tener múltiples `MiembroTaller` con rol
`mandante`, `supervisor` o `mecanico`. Cada `mecanico` **SHALL** tener al menos una
especialidad (`CategoriaServicio`).

#### Scenario: Crear mecánico con especialidad
- GIVEN un taller existente
- WHEN se crea un `MiembroTaller(rol='mecanico')` con una o más especialidades
- THEN el miembro queda persistido y disponible para asignación

#### Scenario: Roles únicos
- GIVEN un taller que ya tiene un `mandante` y un `supervisor`
- WHEN se intenta crear otro `mandante` o `supervisor`
- THEN la operación es rechazada por la restricción de unicidad

### REQ-PROVEEDOR-MODALIDAD
`Taller.modalidad_atencion` **SHALL** ser `en_taller`, `a_domicilio` o `ambas`.
Un taller con `a_domicilio`/`ambas` **SHALL** poder definir `radio_cobertura` y zonas de cobertura.

#### Scenario: Taller mixto
- GIVEN un taller con `modalidad_atencion='ambas'`
- WHEN un cliente busca servicio a domicilio
- THEN el taller es elegible como proveedor a domicilio

### REQ-COMPAT-SIN-EQUIPO
Un taller sin `MiembroTaller` activos **SHALL** seguir operando con el comportamiento
previo (agenda y disponibilidad a nivel taller).
