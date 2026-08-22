# Plantillas Utility de WhatsApp (ventana 24 h)

Meta no permite texto libre fuera de las 24 h. Mecanimovil envía estas plantillas **Utility** (español). Sin ellas, la cotización se comparte con link público y el aviso no sale por el canal.

El nombre de cada plantilla en Meta debe coincidir **exactamente** con el valor de la variable en Render.

## Variables Render

| Variable | Nombre sugerido | Cuerpo |
|---|---|---|
| `WHATSAPP_TEMPLATE_COTIZACION` | `cotizacion_lista` | `{{1}} tiene lista tu cotización de {{2}} por {{3}}. Revísala aquí: {{4}}` |
| `WHATSAPP_TEMPLATE_CITA` | `cita_recordatorio` | `{{1}} te recuerda tu visita: {{2}}. Si necesitas cambiarla, responde este mensaje.` |
| `WHATSAPP_TEMPLATE_AVISO` | `aviso_taller` | `{{1}} te dejó un aviso. Responde este mensaje para continuar.` |
| `WHATSAPP_TEMPLATE_LANG` | `es` | Idioma de las tres |

Variables de cuerpo:

- Cotización: `{{1}}` taller · `{{2}}` servicio · `{{3}}` total · `{{4}}` URL pública
- Cita: `{{1}}` taller · `{{2}}` fecha/hora o “horario por confirmar”
- Aviso: `{{1}}` taller

Opcional: `WHATSAPP_TEMPLATE_COTIZACION_URL_BUTTON=True` si la plantilla de cotización tiene botón URL (dominio fijo + token).

## Cómo crearlas en Meta (WhatsApp Manager)

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

## Cómo pegarlas en Render

Cuando estén **Aprobadas**, en el servicio `mecanimovil-api` (y el worker si lee las mismas env vars):

1. [Render Dashboard](https://dashboard.render.com) → `mecanimovil-api` → **Environment**.
2. Agrega (o edita) estas claves, sin comillas:

```
WHATSAPP_TEMPLATE_COTIZACION=cotizacion_lista
WHATSAPP_TEMPLATE_CITA=cita_recordatorio
WHATSAPP_TEMPLATE_AVISO=aviso_taller
WHATSAPP_TEMPLATE_LANG=es
```

3. Guarda. Render reinicia el servicio. Hasta que existan, WhatsApp solo entrega cotización por **link** y **Enviar aviso** no sale.

## Cómo las usa la app

- **Cotizar** con ventana cerrada: plantilla de cotización si está configurada; si no, link público.
- **Enviar aviso** (franja del chat, solo WhatsApp): cita próxima o horario por confirmar → plantilla de cita; si no → aviso.
- Instagram / Messenger: no hay plantilla; solo link de cotización o esperar al cliente.
