# Configuración Meta — mecanimovil_connect

App: **mecanimovil_connect**  
App ID: `1733581160975981`  
API producción: `https://mecanimovil-api.onrender.com`

> La **App Secret** y el **Verify Token** viven solo en `.env` (local) y en el Dashboard de Render. No van al repositorio.

## 1. Variables de entorno (Render — API + Celery worker)

| Variable | Valor |
|----------|--------|
| `OMNICHANNEL_ENABLED` | `True` |
| `META_APP_ID` | `1733581160975981` |
| `META_APP_SECRET` | *(App Secret de Meta — regenerar si se expuso)* |
| `META_INSTAGRAM_APP_SECRET` | *(solo si el caso de uso Instagram usa Instagram Login; ver abajo)* |
| `META_VERIFY_TOKEN` | *(mismo valor que en el webhook)* |
| `META_OAUTH_REDIRECT_URI` | `https://mecanimovil-api.onrender.com/api/omnichannel/oauth/callback/` |
| `META_GRAPH_API_VERSION` | `v21.0` |
| `META_EMBEDDED_SIGNUP_CONFIG_ID` | *(Configuration ID — ver sección 5)* |
| `META_EMBEDDED_SIGNUP_CONFIG_ID_WHATSAPP` | *(opcional, override por canal)* |
| `META_EMBEDDED_SIGNUP_CONFIG_ID_MESSENGER` | *(opcional)* |
| `META_EMBEDDED_SIGNUP_CONFIG_ID_INSTAGRAM` | **Requerido** para conectar Instagram (ver sección 4.4) |

Tras guardar, redeploy de **mecanimovil-api** y **mecanimovil-celery-worker**.

## 2. Webhook

| Campo | Valor |
|-------|--------|
| Callback URL | `https://mecanimovil-api.onrender.com/api/omnichannel/webhooks/meta/` |
| Verify token | Valor de `META_VERIFY_TOKEN` |

Suscripciones:

| Objeto | Campos |
|--------|--------|
| WhatsApp Business Account | `messages` |
| Page | `messages`, `messaging_postbacks` |
| Instagram | `messages`, `messaging_postbacks` *(mismo webhook URL)* |

## 3. OAuth — Redirect URIs válidas

En **App settings → Basic → Valid OAuth Redirect URIs**:

```
https://mecanimovil-api.onrender.com/api/omnichannel/oauth/callback/
```

En **App Domains** agrega:

- `mecanimovil-api.onrender.com`
- El dominio donde corre **mecanimovil-prov** web (ej. tu dominio Vercel/Render static)

## 4. Embedded Signup (conexión sin fricción para talleres)

Este paso permite que cada taller conecte WhatsApp (y opcionalmente Page/Instagram) **sin pegar Phone Number ID** manualmente.

### 4.1 Crear configuración en Meta Developers

1. [developers.facebook.com](https://developers.facebook.com) → **mecanimovil_connect**.
2. **Use cases** → **Customize** → agrega **Facebook Login for Business** si no está.
3. Ve a **Facebook Login for Business → Configurations** (o **Embedded Signup** dentro de WhatsApp).
4. **Create configuration**:
   - **Login variation:** WhatsApp Embedded Signup (para WhatsApp).
   - **Assets:** WhatsApp Account (permiso *manage*).
   - **Permissions:** `whatsapp_business_management`, `whatsapp_business_messaging`, `business_management`.
5. Copia el **Configuration ID** → `META_EMBEDDED_SIGNUP_CONFIG_ID` en Render.

Para **Messenger**, crea una configuración con asset **Pages** y permisos `pages_messaging`, `pages_show_list`, `pages_read_engagement`, `business_management` → `META_EMBEDDED_SIGNUP_CONFIG_ID_MESSENGER`.

Si solo defines una config global para WhatsApp, úsala en `META_EMBEDDED_SIGNUP_CONFIG_ID`. **Instagram requiere su propia config** (no reutilices la de WhatsApp).

### 4.4 Instagram — mensajes directos (DM)

El error **"Invalid Scopes: instagram_basic, instagram_manage_messages"** aparece si esos permisos se envían en la URL OAuth. En Mecanimovil los permisos de Instagram van **solo** en la Login Configuration de Meta, no en el parámetro `scope`.

**Requisitos del taller (antes de conectar):**

1. Cuenta **Instagram profesional** (Business o Creator).
2. Vinculada a una **Página de Facebook** en [Meta Business Suite](https://business.facebook.com) → Configuración → Cuentas de Instagram.
3. Mensajes de Instagram activados en la app de Instagram → Configuración → Mensajes → Herramientas conectadas.

**Pasos en Meta Developers (ops, una vez):**

1. **mecanimovil_connect** → **Use cases** → agrega **Instagram** (API de mensajería de Instagram) si no está.
2. **Facebook Login for Business → Configurations → Create configuration**:
   - **Login variation:** Facebook Login for Business (no WhatsApp Embedded Signup).
   - **Assets:** Facebook Page (*manage*).
   - **Permissions:** `instagram_manage_messages`, `pages_messaging`, `pages_show_list`, `pages_read_engagement`, `business_management`.
   - **No** agregues `instagram_basic` en la config (no es necesario para DMs y puede fallar en Login for Business).
3. Copia el **Configuration ID** → `META_EMBEDDED_SIGNUP_CONFIG_ID_INSTAGRAM` en Render.
4. **App Review:** solicita `instagram_manage_messages` (Advanced Access) para producción.
5. Webhook (sección 2): suscribe el objeto **Instagram** además de Page y WhatsApp.

**Flujo en la app (igual que Messenger):**

- Web: diálogo embebido FB SDK con `config_id` de Instagram.
- Móvil: popup OAuth (sin `scope` inválidos en la URL).

Tras conectar, el backend obtiene el `instagram_account_id` de la Page y suscribe webhooks de la Page.

**Webhook firma inválida (`Invalid Meta webhook signature`):**

Meta firma los POST con el **App Secret** de la app que envía el webhook. Si en el caso de uso Instagram elegiste **Instagram Login**, Meta puede usar un secret distinto al de `META_APP_SECRET`.

1. Preferido: en el caso de uso Instagram usa **API setup with Facebook Login** (mismo secret que la app `1733581160975981`).
2. Si usas Instagram Login: copia el **Instagram App Secret** del dashboard → `META_INSTAGRAM_APP_SECRET` en Render (API + worker).
3. Siempre sincroniza **App Secret** (Settings → Basic) → `META_APP_SECRET` en Render (API + worker).

### 4.2 Dominios permitidos (SDK web)

En **Facebook Login → Settings**:

- **Allowed domains for the JavaScript SDK:** dominio de la app proveedores web.
- **Valid OAuth Redirect URIs:** incluye la URL del callback del API (sección 3).

### 4.3 Flujo en la app proveedores

| Plataforma | Comportamiento |
|------------|----------------|
| **Web** | Diálogo embebido de Meta (FB SDK) → envía `code` + `waba_id` + `phone_number_id` al backend |
| **iOS / Android** | Abre OAuth en navegador → callback HTML “Cerrar y volver a la app” |

Endpoint nuevo: `POST /api/omnichannel/connections/completar-conexion/` (usado por web embebido).

## 5. Probar desde la app proveedores

1. Perfil → **Canales de mensajería** → **Conectar** WhatsApp / Messenger / Instagram.
2. Completa el flujo Meta (Embedded Signup en web, navegador en móvil).
3. Envía un mensaje de prueba al número/Página conectados.
4. Debe aparecer en **Chats** con badge de canal.

## 6. Nota para talleres

Los talleres **no** configuran Meta ni pegan identificadores técnicos. Solo pulsan **Conectar** en la app.

La configuración de esta guía es **interna de Mecanimovil** (una vez). Sin `META_EMBEDDED_SIGNUP_CONFIG_ID`, WhatsApp no entrega el número al conectar y la conexión fallará hasta que ops lo complete.

## 7. Checklist ops (Mecanimovil)

- [ ] Env vars en Render (API + worker), incl. `META_EMBEDDED_SIGNUP_CONFIG_ID`
- [ ] Webhook verificado
- [ ] OAuth redirect + App Domains
- [ ] Configuration ID WhatsApp creado en Meta
- [ ] `META_EMBEDDED_SIGNUP_CONFIG_ID_INSTAGRAM` + App Review `instagram_manage_messages`
- [ ] Webhook Instagram suscrito (`messages`)
- [ ] Dominio web proveedores en Allowed domains SDK
- [ ] Mensaje inbound + respuesta outbound OK

## Seguridad

Si la App Secret se compartió en un canal inseguro, **regenera la clave** en Meta → App settings → Basic → **Reset** y actualiza Render.
