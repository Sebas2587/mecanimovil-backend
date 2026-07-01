# notificaciones-push Specification

## Purpose
Contrato de notificaciones push (Expo + Web Push) para proveedores, incluyendo
anti-duplicado web/native y tipos de evento críticos del taller.

## Requirements

### Requirement: Origen de suscripción web
WebPushSubscription SHALL registrar de qué app proviene la suscripción.

#### Scenario: Registro desde app proveedores
- GIVEN POST `/usuarios/registrar-web-push/` con `app_origen: proveedor`
- THEN la suscripción queda con `app_origen=proveedor`

### Requirement: Anti-duplicado web y nativo
Si el usuario tiene PushToken nativo activo reciente, Web Push SHALL omitirse.

#### Scenario: Usuario con app nativa
- GIVEN PushToken activo registrado en últimos 30 días
- WHEN `send_expo_push_notification` encola push
- THEN se envía Expo
- AND `_send_web_push_to_user` no envía

#### Scenario: Usuario solo web
- GIVEN sin PushToken activo y WebPushSubscription activa
- WHEN se encola push
- THEN `_send_web_push_to_user` entrega notificación

### Requirement: Solicitud por vencer
Tarea periódica SHALL alertar proveedores elegibles antes de `fecha_expiracion`.

#### Scenario: Solicitud abierta sin oferta del proveedor
- GIVEN solicitud `publicada`/`con_ofertas` con expiración en 30–60 min
- AND proveedor elegible sin oferta activa
- WHEN corre `recordar_solicitudes_por_vencer_proveedor`
- THEN push `solicitud_por_vencer` con `solicitud_id`, `minutos_restantes`

### Requirement: Checklist pendiente
Creación de ChecklistInstance PENDIENTE SHALL notificar al proveedor.

#### Scenario: Orden confirmada con template
- GIVEN orden confirmada y checklist creado estado PENDIENTE
- WHEN se invoca hook post-creación
- THEN push `checklist_pendiente` con `orden_id`, `checklist_id`, `solicitud_id` opcional
