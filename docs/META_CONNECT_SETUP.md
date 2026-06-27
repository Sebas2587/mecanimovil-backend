# Configuración Meta — mecanimovil_connect

App: **mecanimovil_connect**  
App ID: `1733581160975981`

> La **App Secret** y el **Verify Token** viven solo en `.env` (local) y en el Dashboard de Render. No van al repositorio.

## 1. Variables de entorno (Render — servicio `mecanimovil-api`)

En [Render Dashboard](https://dashboard.render.com) → `mecanimovil-api` → Environment:

| Variable | Valor |
|----------|--------|
| `OMNICHANNEL_ENABLED` | `True` |
| `META_APP_ID` | `1733581160975981` |
| `META_APP_SECRET` | *(tu App Secret de Meta)* |
| `META_VERIFY_TOKEN` | *(mismo valor que en el paso 2 webhook)* |
| `META_OAUTH_REDIRECT_URI` | `https://api.mecanimovil.com/api/omnichannel/oauth/callback/` |
| `META_GRAPH_API_VERSION` | `v21.0` |
| `META_EMBEDDED_SIGNUP_CONFIG_ID` | *(opcional, tras crear Embedded Signup)* |

Repite las mismas variables en **mecanimovil-celery-worker** (procesa webhooks y envío).

Tras guardar, redeploy de API + worker.

## 2. Webhook en Meta Developers

1. Abre [developers.facebook.com](https://developers.facebook.com) → **mecanimovil_connect**.
2. **Use cases** o **Products** → agrega si faltan:
   - **WhatsApp** → Set up
   - **Messenger** (desde Facebook Login for Business o Pages)
   - **Instagram** (mensajería vía API con Page vinculada)
3. **Webhooks** (o WhatsApp → Configuration → Webhook):

   | Campo | Valor |
   |-------|--------|
   | Callback URL | `https://api.mecanimovil.com/api/omnichannel/webhooks/meta/` |
   | Verify token | El valor de `META_VERIFY_TOKEN` en Render |

4. Suscríbete a (según producto):
   - **WhatsApp:** `messages` (campo messages en WhatsApp Business Account)
   - **Page:** `messages`, `messaging_postbacks`
   - **Instagram:** vía la misma suscripción de Page si IG está vinculada

5. Pulsa **Verify and save**. Debe responder 200 (GET con `hub.challenge`).

## 3. OAuth — Redirect URIs válidas

En **App settings → Basic** o **Facebook Login → Settings → Valid OAuth Redirect URIs**, agrega:

```
https://api.mecanimovil.com/api/omnichannel/oauth/callback/
```

Para desarrollo local con ngrok (opcional):

```
https://TU-SUBDOMINIO.ngrok-free.app/api/omnichannel/oauth/callback/
```

Y en `.env` local ajusta `META_OAUTH_REDIRECT_URI` a esa URL.

## 4. Permisos / App Review (producción)

Solicita acceso avanzado cuando vayas a producción con talleres reales:

- `whatsapp_business_messaging`
- `whatsapp_business_management`
- `pages_messaging`
- `pages_show_list`
- `instagram_manage_messages`
- `business_management`

En **modo Development** puedes probar con usuarios de prueba de la app y cuentas Business de prueba.

## 5. Embedded Signup (recomendado para talleres)

1. [Meta Business Suite](https://business.facebook.com) → **Settings** → **WhatsApp accounts** → **Embedded Signup** (o documentación Tech Provider).
2. Crea una configuración de Embedded Signup vinculada a `mecanimovil_connect`.
3. Copia el **Configuration ID** → `META_EMBEDDED_SIGNUP_CONFIG_ID` en Render.

Sin este ID, el flujo OAuth básico sigue funcionando; Embedded Signup mejora el onboarding de WABA por taller.

## 6. Probar desde la app proveedores

1. Deploy con `OMNICHANNEL_ENABLED=True` y migraciones aplicadas.
2. Perfil → **Canales de mensajería** → **Conectar** WhatsApp / Messenger / Instagram.
3. Envía un mensaje de prueba al número/Página conectados.
4. Debe aparecer en **Chats** con badge de canal en pocos segundos.

## 7. Checklist rápido

- [ ] Env vars en Render (API + Celery worker)
- [ ] Webhook verificado en Meta
- [ ] OAuth redirect URI registrada
- [ ] `python manage.py migrate omnichannel chat` en deploy
- [ ] Mensaje de prueba inbound + respuesta outbound

## Seguridad

Si la App Secret se compartió en un canal inseguro, **regenera la clave** en Meta → App settings → Basic → **Reset** y actualiza Render + `.env` local.
