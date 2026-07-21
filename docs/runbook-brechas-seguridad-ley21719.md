# Runbook de respuesta a brechas de seguridad — Ley 21.719 art. 14 sexies

**Responsable:** Mecanimovil SpA · soporte@mecanimovil.cl  
**Última revisión:** julio 2026

## 1. Detección y contención (0–4 h)

1. Confirmar el incidente (logs, alertas, reporte interno/externo).
2. Aislar sistemas afectados (rotar credenciales, revocar tokens, bloquear IPs).
3. Preservar evidencia (logs, snapshots DB, timestamps).
4. Designar responsable de incidente y canal interno (Slack/email).

## 2. Evaluación de impacto (4–24 h)

- Identificar **qué datos personales** se vieron expuestos (PII, patente, ubicación, pagos, etc.).
- Estimar **titulares afectados** y si hay riesgo elevado (credenciales, datos financieros, menores).
- Documentar vector de ataque y extensión temporal.

## 3. Notificación a titulares

- Notificar **sin dilación indebida** cuando exista riesgo para derechos del titular.
- Contenido mínimo: qué ocurrió, datos afectados, medidas tomadas, recomendaciones (cambio de contraseña), contacto soporte@mecanimovil.cl.
- Canales: email registrado, push operativo, aviso in-app si aplica.

## 4. Notificación a la Agencia de Protección de Datos

- Cuando la normativa lo exija, notificar a la **Agencia de Protección de Datos Personales** con el detalle del incidente y medidas adoptadas.
- Mantener registro interno del envío (fecha, referencia, adjuntos).

## 5. Remediación y cierre

- Parchear vulnerabilidad y validar en staging.
- Revisar accesos públicos (`AllowAny`), tokens sin TTL, enumeración de IDs.
- Post-mortem interno: causa raíz, acciones preventivas, actualizar este runbook.

## 6. Cookies / analytics web

**Estado actual (jul 2026):** la SPA web de `mecanimovil-usuarios` **no integra SDK de analytics/marketing** (Mixpanel, GA, Meta Pixel, etc.). Solo cookies técnicas de sesión/navegación.

- **Banner CMP:** implementar **solo si** se agrega tracking no esencial en el futuro.
- Documentar la decisión en cada release que incorpore analytics.

## Referencias técnicas en producto

| Superficie | Control |
|---|---|
| Eliminar cuenta | `POST /usuarios/eliminar-cuenta/` |
| Export ARCOP | `GET /usuarios/mis-datos/export/` |
| Consentimiento | `POST /usuarios/consentimiento/registrar/` |
| Ficha pública | opt-in + token `/vehiculos/ficha-publica-token/<token>/` |
| Informe/cotización | TTL 30 días, HTTP 410 si expirado |
