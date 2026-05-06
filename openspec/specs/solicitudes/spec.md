# solicitudes Specification

## Purpose
Gestionar las solicitudes de servicio que los usuarios envían y que los proveedores
pueden aceptar o rechazar. Una solicitud aceptada genera una orden.

## Requirements

### Requirement: Creación de solicitud
Un usuario_final puede crear una solicitud especificando tipo de servicio, vehículo y ubicación.

#### Scenario: Solicitud creada exitosamente
- GIVEN un usuario_final autenticado con un vehículo registrado
- WHEN hace POST /api/solicitudes/ con servicio, vehiculo_id y descripción
- THEN se crea la solicitud en estado=pendiente
- AND los proveedores disponibles reciben notificación push

#### Scenario: Solicitud sin vehículo registrado
- GIVEN un usuario_final sin vehículos en su perfil
- WHEN intenta crear una solicitud
- THEN recibe status 400 con mensaje "Debes registrar un vehículo primero"

### Requirement: Respuesta del proveedor
El proveedor puede aceptar o rechazar una solicitud dentro de un tiempo límite.

#### Scenario: Proveedor acepta solicitud
- GIVEN una solicitud en estado=pendiente visible para el proveedor
- WHEN el proveedor hace POST /api/solicitudes/{id}/aceptar/
- THEN la solicitud pasa a estado=aceptada
- AND se crea automáticamente una Orden asociada
- AND se notifica al usuario

#### Scenario: Proveedor rechaza solicitud
- GIVEN una solicitud en estado=pendiente
- WHEN el proveedor hace POST /api/solicitudes/{id}/rechazar/ con motivo
- THEN la solicitud pasa a estado=rechazada
- AND se notifica al usuario con el motivo

#### Scenario: Solicitud sin respuesta (timeout)
- GIVEN una solicitud pendiente sin respuesta por 30 minutos
- WHEN el Celery beat corre la tarea de expiración
- THEN la solicitud pasa a estado=expirada
- AND se notifica al usuario para crear nueva solicitud
