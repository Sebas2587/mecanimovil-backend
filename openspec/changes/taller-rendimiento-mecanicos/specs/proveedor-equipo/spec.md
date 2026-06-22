# Delta: proveedor-equipo (rendimiento)

## ADDED Requirements

### REQ-RENDIMIENTO-MECANICOS
La app de proveedores **SHALL** exponer el rendimiento por mecánico: número de órdenes
asignadas y completadas en un rango de fechas.

#### Scenario: Rendimiento del equipo
- GIVEN un taller con mecánicos que tienen órdenes asignadas
- WHEN el dueño consulta el rendimiento del equipo
- THEN recibe, por mecánico, los conteos de órdenes asignadas y completadas
