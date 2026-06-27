# omnichannel-messaging Specification

## Purpose

Integración Meta (WhatsApp, Messenger, Instagram) para proveedores: webhooks,
conexión OAuth, inbox unificado, tiempo real y push.

## Requirements

### Requirement: Webhook Meta verificado
Meta SHALL poder verificar el endpoint de webhook.

#### Scenario: Verificación GET hub.challenge
- GIVEN `META_VERIFY_TOKEN` configurado
- WHEN Meta envía GET con `hub.verify_token` correcto
- THEN responde 200 con `hub.challenge`

### Requirement: Mensaje entrante identificado por canal
Todo mensaje inbound SHALL persistirse con `source_channel` y broadcast con `channel`.

#### Scenario: WhatsApp inbound
- GIVEN taller con WhatsApp conectado y enabled
- WHEN cliente envía mensaje al número del taller
- THEN se crea Message con direction=inbound, source_channel=WHATSAPP
- AND WS payload incluye `channel: whatsapp`
- AND push título incluye prefijo "WhatsApp"

### Requirement: Conexión por proveedor
Proveedor SHALL conectar su cuenta Meta vía Embedded Signup.

#### Scenario: Iniciar conexión WhatsApp
- GIVEN proveedor autenticado sin WhatsApp conectado
- WHEN llama `iniciar-conexion?channel=whatsapp`
- THEN recibe `auth_url` para Embedded Signup

#### Scenario: Callback exitoso
- GIVEN OAuth completado en Meta
- WHEN callback recibe code válido
- THEN connection status=conectada con phone_number_id y display_identifier

### Requirement: Toggle canal
Proveedor SHALL deshabilitar canal sin desconectar tokens.

#### Scenario: Canal deshabilitado
- GIVEN connection enabled=false
- WHEN llega webhook para ese phone_number_id
- THEN mensaje ignorado (204/log)

### Requirement: Outbound dentro ventana
Proveedor SHALL responder desde app y mensaje llega al cliente externo.

#### Scenario: Respuesta WhatsApp
- GIVEN conversación WHATSAPP activa (<24h)
- WHEN proveedor send_message
- THEN Celery envía Graph API y cliente recibe texto

### Requirement: Inbox unificado
API SHALL fusionar chats oferta + conversaciones omnicanal.

#### Scenario: Lista inbox proveedor
- GIVEN conversación OMNICHANNEL sin oferta
- WHEN GET inbox
- THEN aparece con channel badge y external_contact_name
