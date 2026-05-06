# notificaciones-push Specification

## Purpose
Enviar notificaciones push a la app mediante Expo Push Notifications Service.
Los tokens de dispositivo se registran y asocian al usuario/proveedor.

## Requirements

### Requirement: Registro de token de dispositivo
Al iniciar sesión en la app, el dispositivo registra su Expo push token.

#### Scenario: Token registrado correctamente
- GIVEN un usuario autenticado con Expo token válido
- WHEN la app hace POST /api/notificaciones/token/ con el token del dispositivo
- THEN el token se asocia al usuario en la base de datos
- AND reemplaza cualquier token anterior del mismo dispositivo

### Requirement: Envío de notificaciones por eventos del sistema
El sistema envía notificaciones automáticas al ocurrir eventos clave.

#### Scenario: Notificación al usuario cuando proveedor acepta solicitud
- GIVEN una solicitud en estado=pendiente
- WHEN el proveedor la acepta
- THEN el sistema envía push al usuario: "Tu solicitud fue aceptada"
- AND se registra el envío en el log de notificaciones

#### Scenario: Notificación al proveedor cuando llega nueva solicitud
- GIVEN un proveedor activo con token registrado
- WHEN se crea una solicitud compatible con sus especialidades
- THEN recibe push: "Nueva solicitud disponible cerca de ti"

#### Scenario: Token inválido o expirado
- GIVEN un token de dispositivo que ya no es válido
- WHEN Expo devuelve DeviceNotRegistered en el envío
- THEN el sistema elimina el token de la base de datos
- AND no reintenta el envío
