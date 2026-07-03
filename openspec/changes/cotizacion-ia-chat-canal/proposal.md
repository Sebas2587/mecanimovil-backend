# cotizacion-ia-chat-canal

## Why

El mandante del taller cotiza manualmente por chat omnicanal (WhatsApp, etc.) sin apoyo de IA ni flujo estructurado de aceptación previa al agendamiento.

## What Changes

- Modelos `CotizacionCanal`, `CotizacionCanalPlantilla` en `ordenes`.
- Servicio `asistente_cotizacion/` (Gemini HTTP, patrón asistente diagnóstico).
- API REST cotizaciones-canal + plantillas.
- WhatsApp interactive (Aceptar/Rechazar) + webhook.
- Feature flag `ASISTENTE_COTIZACION_IA_ENABLED`.

## Scope (out)

- LangChain / web scraping del prototipo `analizador_fallas.py`.
- Cobro Mercado Pago en cotización.
- Cotización IA en marketplace `OfertaProveedor`.
- Página web pública de aceptación.

## Requirements

- REQ-COT-IA-GENERAR: POST genera borrador con servicio, repuestos, mano de obra, totales.
- REQ-COT-IA-VEHICULO: patente API + contexto_motor (patente > servicio mal asignado).
- REQ-COT-EDITAR: mandante edita cantidades/precios antes de enviar.
- REQ-COT-ENVIAR: POST enviar → Message + WhatsApp interactive; estado `enviada`.
- REQ-COT-ACEPTAR: click cliente → `aceptada`.
- REQ-COT-AGENDAR: desde `aceptada`, prefill agendamiento.
- REQ-COT-PLANTILLA: guardar/reutilizar plantillas del taller.
- REQ-COT-FALLBACK: Gemini off/falla → `disponible=false`, formulario manual sigue.
- REQ-COT-PERMISO: solo mandante/supervisor del taller (no mecánico v1).
