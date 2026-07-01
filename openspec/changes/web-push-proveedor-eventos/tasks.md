# Tasks: web-push-proveedor-eventos (backend)

## Modelo y routing
- [x] Migración `app_origen` en WebPushSubscription
- [x] `registrar_web_push` acepta `app_origen`
- [x] `_user_has_active_native_push` + skip web en `_send_web_push_to_user`
- [x] Throttle + channel_id para `solicitud_por_vencer`, `checklist_pendiente`

## Eventos nuevos
- [x] `recordar_solicitudes_por_vencer_proveedor` en ordenes/tasks.py
- [x] Beat schedule cada 30 min en celery.py
- [x] `notificar_checklist_pendiente_proveedor` + hooks en ordenes/views.py

## OpenSpec
- [x] specs/notificaciones-push/spec.md
