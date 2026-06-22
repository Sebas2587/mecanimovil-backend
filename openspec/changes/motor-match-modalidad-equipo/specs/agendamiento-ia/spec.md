# Delta: agendamiento-ia (match por modalidad y equipo)

## ADDED Requirements

### REQ-MATCH-MODALIDAD-EQUIPO
El motor de match **SHALL** considerar la modalidad de atención del proveedor y la
disponibilidad de mecánicos aptos del taller.

#### Scenario: Taller mixto en búsqueda a domicilio
- GIVEN un taller con `modalidad_atencion='ambas'` y un mecánico domicilio apto
- WHEN el cliente busca un servicio a domicilio
- THEN el taller aparece entre los candidatos

#### Scenario: Equipo sin especialidad
- GIVEN un taller cuyos mecánicos con la especialidad requerida están deshabilitados
- WHEN el cliente busca ese servicio
- THEN el taller no aparece como candidato

#### Scenario: Taller sin equipo
- GIVEN un taller sin `MiembroTaller`
- WHEN el cliente busca un servicio que el taller ofrece
- THEN el taller aparece como antes (sin regresión)
