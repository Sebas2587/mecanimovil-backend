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
| `META_VERIFY_TOKEN` | *(mismo valor que en el webhook)* |
| `META_OAUTH_REDIRECT_URI` | `https://mecanimovil-api.onrender.com/api/omnichannel/oauth/callback/` |
| `META_GRAPH_API_VERSION` | `v21.0` |
| `META_EMBEDDED_SIGNUP_CONFIG_ID` | *(Configuration ID — ver sección 5)* |
| `META_EMBEDDED_SIGNUP_CONFIG_ID_WHATSAPP` | *(opcional, override por canal)* |
| `META_EMBEDDED_SIGNUP_CONFIG_ID_MESSENGER` | *(opcional)* |
| `META_EMBEDDED_SIGNUP_CONFIG_ID_INSTAGRAM` | *(opcional)* |

Tras guardar, redeploy de **mecanimovil-api** y **mecanimovil-celery-worker**.

## 2. Webhook

| Campo | Valor |
|-------|--------|
| Callback URL | `https://mecanimovil-api.onrender.com/api/omnichannel/webhooks/meta/` |
| Verify token | Valor de `META_VERIFY_TOKEN` |

Suscripciones: WhatsApp `messages`; Page `messages`, `messaging_postbacks`.

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

Para **Messenger** e **Instagram**, crea configuraciones adicionales con assets **Pages** (y permisos `pages_messaging`, `pages_show_list`, `instagram_manage_messages`) y guárdalas en:

- `META_EMBEDDED_SIGNUP_CONFIG_ID_MESSENGER`
- `META_EMBEDDED_SIGNUP_CONFIG_ID_INSTAGRAM`

Si solo defines una config global, úsala en `META_EMBEDDED_SIGNUP_CONFIG_ID`.

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

## 6. Fallback Phone Number ID

Si Embedded Signup no está configurado o Meta no devuelve el número automáticamente, la app muestra un campo para pegar el **Phone Number ID** desde Meta Business Suite → WhatsApp → Configuración API.

## 7. Checklist

- [ ] Env vars en Render (API + worker), incl. `META_EMBEDDED_SIGNUP_CONFIG_ID`
- [ ] Webhook verificado
- [ ] OAuth redirect + App Domains
- [ ] Configuration ID creado en Meta
- [ ] Dominio web proveedores en Allowed domains SDK
- [ ] Mensaje inbound + respuesta outbound OK

## Seguridad

Si la App Secret se compartió en un canal inseguro, **regenera la clave** en Meta → App settings → Basic → **Reset** y actualiza Render.
