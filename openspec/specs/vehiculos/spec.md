# vehiculos Specification

## Purpose
Gestión de vehículos registrados por el usuario. Un vehículo es requisito previo
para crear solicitudes de servicio.

## Requirements

### Requirement: CRUD de vehículos del usuario
El usuario puede registrar, editar y eliminar sus vehículos.

#### Scenario: Registrar vehículo
- GIVEN un usuario_final autenticado
- WHEN hace POST /api/vehiculos/ con marca, modelo, año, patente
- THEN el vehículo queda asociado al usuario
- AND puede usarse en nuevas solicitudes de servicio

#### Scenario: Patente duplicada
- GIVEN un vehículo ya registrado con una patente
- WHEN otro usuario intenta registrar la misma patente
- THEN recibe status 400 con mensaje "Patente ya registrada"

#### Scenario: Eliminar vehículo con órdenes activas
- GIVEN un vehículo asociado a una orden en estado=en_progreso
- WHEN el usuario intenta eliminarlo
- THEN recibe status 400 con mensaje "No puedes eliminar un vehículo con órdenes activas"

### Requirement: Historial de servicios por vehículo
El usuario puede ver el historial de órdenes completadas por vehículo.

#### Scenario: Ver historial de un vehículo
- GIVEN un vehículo con órdenes completadas
- WHEN el usuario hace GET /api/vehiculos/{id}/historial/
- THEN recibe la lista de órdenes completadas con fecha, servicio y proveedor
