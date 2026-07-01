# web-push-proveedor-eventos (backend)

## Why

La app proveedores web necesita los mismos eventos push que Expo, más tipos
faltantes (vencimiento de solicitud, checklist pendiente), sin duplicar alertas
en usuarios con app nativa instalada.

## What Changes

- `WebPushSubscription.app_origen` (`proveedor` | `usuario`).
- Anti-duplicado: omitir Web Push si hay `PushToken` nativo activo reciente.
- Celery `recordar_solicitudes_por_vencer_proveedor` cada 30 min.
- Helper `notificar_checklist_pendiente_proveedor` en creación de checklist.
- Throttle y channel mapping para nuevos tipos push.

## Requirements

- REQ-PUSH-APP-ORIGEN: registrar-web-push SHALL aceptar `app_origen`.
- REQ-PUSH-NO-DUP: Web Push SHALL omitirse si PushToken nativo activo (<30 días).
- REQ-PUSH-SOL-VENCER: tarea periódica SHALL encolar `solicitud_por_vencer`.
- REQ-PUSH-CHECKLIST: creación ChecklistInstance PENDIENTE SHALL encolar `checklist_pendiente`.
