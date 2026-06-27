# Tasks: omnichannel-meta-messaging (backend)

## Fase 0 — Meta Platform
- [x] Documentar Runbook Meta en `design.md` + `docs/META_CONNECT_SETUP.md`
- [x] App Meta creada: mecanimovil_connect (`1733581160975981`)
- [x] Variables locales en `.env` (gitignored)
- [ ] Configurar env vars en Render (API + Celery worker)
- [x] Comentar env vars en `render.yaml`

## Fase 1 — Backend core
- [x] App `omnichannel`: models, migrations, admin
- [x] `OmnichannelService` (ingest, resolve, broadcast)
- [x] Webhook GET/POST + Celery `process_meta_webhook`
- [x] Feature flag `OMNICHANNEL_ENABLED` en settings
- [x] Registrar URLs en `mecanimovilapp/urls.py`

## Fase 2 — Conexión OAuth
- [x] `ProviderChannelConnectionViewSet` (estado, iniciar-conexion, desconectar, toggle)
- [x] OAuth callback `/api/omnichannel/oauth/callback/`
- [x] `MetaGraphClient` helper

## Fase 3 — Chat extendido
- [x] Migración chat: `source_channel`, `external_contact`, `direction`, etc.
- [x] `send_message` outbound Celery para canales externos
- [x] `GET /api/chat/conversations/inbox/` unificado
- [x] Payload WS + push con `channel`, `external_contact_*`
- [x] Endpoint vincular solicitud

## Fase 4 — Tests
- [x] `tests/test_omnichannel.py`
- [x] `tests/test_inbox_api.py`
- [ ] Ejecutar suite completa en CI con PostGIS

## Verificación supervisor (no archivar sin 13/13)
- [ ] V1 Webhook verify Meta Dashboard
- [ ] V2 Conectar WhatsApp Embedded Signup
- [ ] V3 Inbound WhatsApp WS <3s badge
- [ ] V4 Push WhatsApp background + deep link
- [ ] V5 Outbound WhatsApp al teléfono
- [ ] V6 Messenger inbound/outbound
- [ ] V7 Instagram inbound/outbound
- [ ] V8 Inbox general sin solicitud
- [ ] V9 Vincular solicitud
- [ ] V10 Toggle deshabilitar canal
- [ ] V11 Desconectar reconexión limpia
- [ ] V12 `pytest apps/omnichannel/` verde (CI/PostGIS)
- [ ] V13 Regresión chat in-app oferta/solicitud
