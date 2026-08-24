# Plantillas Utility de WhatsApp (ventana 24 h)

**Estado actual: apagadas.** `WHATSAPP_TEMPLATES_ENABLED=False`.

El taller no recontacta por plantilla. Cotiza con IA y **comparte el link** por el canal que quiera (WhatsApp personal, Instagram, etc.). Las reglas de Meta siguen: fuera de 24 h no hay texto libre en el chat conectado.

Para encenderlas más adelante: aprobar las 3 plantillas en Meta y poner `WHATSAPP_TEMPLATES_ENABLED=True` + los nombres en Render.

## Variables Render

| Variable | Nombre sugerido | Cuerpo |
|---|---|---|
| `WHATSAPP_TEMPLATES_ENABLED` | `False` | Kill switch. Por ahora `False`. |
| `WHATSAPP_TEMPLATE_COTIZACION` | `cotizacion_lista` | `{{1}} tiene lista tu cotización de {{2}} por {{3}}. Revísala aquí: {{4}}` |
| `WHATSAPP_TEMPLATE_CITA` | `cita_recordatorio` | `{{1}} te recuerda tu visita: {{2}}. Si necesitas cambiarla, responde este mensaje.` |
| `WHATSAPP_TEMPLATE_AVISO` | `aviso_taller` | `{{1}} te dejó un aviso. Responde este mensaje para continuar.` |
| `WHATSAPP_TEMPLATE_LANG` | `es` | Idioma de las tres |

Variables de cuerpo:

- Cotización: `{{1}}` taller · `{{2}}` servicio · `{{3}}` total · `{{4}}` URL pública
- Cita: `{{1}}` taller · `{{2}}` fecha/hora o “horario por confirmar”
- Aviso: `{{1}}` taller

Opcional: `WHATSAPP_TEMPLATE_COTIZACION_URL_BUTTON=True` si la plantilla de cotización tiene botón URL (dominio fijo + token).

## Cómo crearlas en Meta (cuando se reactive)

Hace falta un WhatsApp Business Account (WABA) ya conectado (el de Embedded Signup de Mecanimovil).

1. Entra a [WhatsApp Manager](https://business.facebook.com/wa/manage/message-templates/) con la cuenta de Meta Business que tiene el WABA.
2. En el menú izquierdo: **Plantillas de mensajes** → **Crear plantilla** (no uses la librería prearmada).
3. Elige categoría **Utilidad** (Utility). No elijas Marketing: cuesta más y Meta puede rechazar el recontacto.
4. Idioma: **Español** (`es`). Si Meta solo ofrece `es_CL` / `es_ES`, créala en ese idioma y pon el mismo código en `WHATSAPP_TEMPLATE_LANG`.
5. Nombre (minúsculas y `_`, sin espacios). Crea **tres** plantillas:

### `cotizacion_lista`

- Cuerpo: `{{1}} tiene lista tu cotización de {{2}} por {{3}}. Revísala aquí: {{4}}`
- Ejemplos que pide Meta (obligatorios): `Taller Sur` · `Diagnóstico` · `$40.000` · `https://mecanimovil.com/c/ejemplo`
- Sin botones (el link va en `{{4}}`).

### `cita_recordatorio`

- Cuerpo: `{{1}} te recuerda tu visita: {{2}}. Si necesitas cambiarla, responde este mensaje.`
- Ejemplos: `Taller Sur` · `22/08/2026 a las 10:00`

### `aviso_taller`

- Cuerpo: `{{1}} te dejó un aviso. Responde este mensaje para continuar.`
- Ejemplo: `Taller Sur`

6. Enviar a revisión. Meta suele tardar minutos u horas. El estado debe quedar **Aprobada**.
7. Si la rechazan: quita tono promocional (“oferta”, “descuento”) y reenvía como Utility.

## Cómo pegarlas en Render (cuando se reactive)

Cuando estén **Aprobadas**, en el servicio `mecanimovil-api`:

1. [Render Dashboard](https://dashboard.render.com) → `mecanimovil-api` → **Environment**.
2. Agrega (o edita) estas claves, sin comillas:

```
WHATSAPP_TEMPLATES_ENABLED=True
WHATSAPP_TEMPLATE_COTIZACION=cotizacion_lista
WHATSAPP_TEMPLATE_CITA=cita_recordatorio
WHATSAPP_TEMPLATE_AVISO=aviso_taller
WHATSAPP_TEMPLATE_LANG=es
```

3. Guarda. Render reinicia el servicio.

## Cómo las usa la app

- **Cotizar** con ventana abierta: el agente IA envía la cotización al chat del canal.
- **Cotizar** con ventana cerrada (hoy): link público; el taller lo comparte a mano.
- Instagram / Messenger: nunca hay plantilla; solo link o esperar al cliente.
- **Enviar aviso** por plantilla queda en el backend, apagado hasta que se encienda el flag.
