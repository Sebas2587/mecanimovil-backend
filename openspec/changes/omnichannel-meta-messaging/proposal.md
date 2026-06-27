# omnichannel-meta-messaging

## Why

Los talleres reciben consultas por WhatsApp, Facebook e Instagram fuera del chat in-app.
Necesitan un inbox unificado en mecanimovil-prov con identificador de canal, tiempo real
y push, conectando sus propias cuentas Meta sin desinstalar WhatsApp personal.

## What Changes

- Nueva app Django `omnichannel` (webhooks Meta, conexiones por proveedor, Celery outbound).
- Extensión de `Conversation`/`Message` con `source_channel`, contactos externos.
- API inbox unificado + payload WS/push con campo `channel`.
- Feature flag `OMNICHANNEL_ENABLED`.

## Scope (in)

| Área | Entregable |
|------|------------|
| Meta Platform | Runbook Fase 0 (App Tech Provider, Embedded Signup, webhooks) |
| Backend | Modelos, webhook, OAuth conexión, outbound, inbox API, tests |
| Push/WS | Reutilizar `nuevo_mensaje_chat` + `send_expo_push_notification` |

## Scope (out)

- App usuarios respondiendo por Meta
- Plantillas WhatsApp fuera ventana 24h (Fase 2)
- BSP terceros (Twilio)

## Requirements

- REQ-OMNI-CHANNEL-ID: todo mensaje entrante SHALL incluir `channel` (whatsapp|messenger|instagram|app).
- REQ-OMNI-INBOX-GENERAL: conversaciones sin solicitud/oferta SHALL aparecer en inbox proveedor.
- REQ-OMNI-LINK-SOLICITUD: proveedor MAY vincular conversación omnicanal a solicitud existente.
- REQ-OMNI-REALTIME: mensaje inbound SHALL broadcast WS a `proveedor_{user_id}` en <3s.
- REQ-OMNI-PUSH: mensaje inbound SHALL encolar push Expo con prefijo de canal.
- REQ-OMNI-TOGGLE: proveedor SHALL poder habilitar/deshabilitar cada canal.
- REQ-OMNI-OAUTH: conexión SHALL usar Embedded Signup Meta (patrón Mercado Pago).
