# Delta: agendamiento-disponibilidad (asignación de técnico)

## ADDED Requirements

### REQ-ASIGNACION-AUTOMATICA
Al crear una `SolicitudServicio` para un taller con equipo, el sistema **SHALL** asignar
`mecanico_asignado` a un `MiembroTaller(rol='mecanico')` apto (especialidad + modalidad)
y libre en el slot, con balanceo de carga.

#### Scenario: Asignación al confirmar
- GIVEN un taller con 2 mecánicos aptos y libres
- WHEN el cliente confirma la cita en un slot
- THEN la orden queda con `mecanico_asignado` = el de menor carga

#### Scenario: Sin técnico disponible
- GIVEN ningún mecánico apto libre en el slot
- WHEN se crea la orden
- THEN se crea con `mecanico_asignado=null` para reasignación manual
