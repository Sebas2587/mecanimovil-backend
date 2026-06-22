# Delta: agendamiento-disponibilidad (por mecánico)

## ADDED Requirements

### REQ-DISPONIBILIDAD-POR-MECANICO
Cuando el taller tiene mecánicos `activo=True`, `disponibilidad_con_duracion` **SHALL**
calcular los slots como la unión de las ventanas libres de cada mecánico apto
(especialidad requerida + `modalidad_tecnico` compatible).

#### Scenario: Unión de agendas
- GIVEN un taller con mecánico A libre 09:00-12:00 y mecánico B libre 14:00-18:00, ambos con la especialidad
- WHEN el cliente consulta disponibilidad para un servicio de esa especialidad
- THEN se ofrecen slots en ambas ventanas

#### Scenario: Mecánico deshabilitado
- GIVEN el único mecánico apto está `activo=False`
- WHEN el cliente consulta disponibilidad
- THEN no se ofrecen slots para esa especialidad

#### Scenario: Fallback sin equipo
- GIVEN un taller sin `MiembroTaller`
- WHEN el cliente consulta disponibilidad
- THEN se usa el `HorarioProveedor` a nivel taller (comportamiento previo)
