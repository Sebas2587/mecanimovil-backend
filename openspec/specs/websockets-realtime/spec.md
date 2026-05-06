# websockets-realtime Specification

## Purpose
Comunicación en tiempo real entre usuarios y proveedores durante el flujo de una orden
activa. Usa Django Channels con Redis como channel layer.

## Requirements

### Requirement: Conexión al canal de orden
Cada orden activa tiene un canal WebSocket dedicado.

#### Scenario: Usuario conecta al canal de su orden
- GIVEN una orden en estado=en_progreso con un usuario autenticado
- WHEN la app abre conexión WS a ws://api/ws/ordenes/{orden_id}/
- THEN la conexión se acepta y el usuario queda suscrito al canal

#### Scenario: Conexión sin token JWT
- GIVEN una solicitud WS sin Authorization header válido
- WHEN intenta conectar
- THEN la conexión se rechaza con código 4001

### Requirement: Mensajes en tiempo real
Ambos actores pueden enviarse mensajes de texto durante la orden.

#### Scenario: Proveedor envía actualización de estado
- GIVEN una orden en_progreso con proveedor conectado
- WHEN el proveedor envía mensaje {"type": "status_update", "message": "Llegando en 10 min"}
- THEN el usuario recibe el mensaje en tiempo real vía WS
- AND el mensaje se persiste en base de datos

#### Scenario: Usuario recibe actualización de ubicación
- GIVEN proveedor en camino con GPS activo
- WHEN el proveedor envía {"type": "location", "lat": x, "lng": y}
- THEN el usuario recibe las coordenadas actualizadas
