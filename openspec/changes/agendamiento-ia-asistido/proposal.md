# Propuesta: Asistente IA de agendamiento (catálogo + necesidad)

## Why
El usuario espera ofertas manuales pese a catálogo configurado; no siempre sabe qué servicio pedir. Se requiere asistencia en creación (texto/voz en cliente), matching a `OfertaServicio`, comparación de hasta 3 candidatos y confirmación del proveedor sin recotizar desde cero.

## What Changes
- Backend: `MotorAgendamientoInteligente` (necesidad, match, confirmación), endpoints stateless de consulta, extensión `OfertaProveedor` (`origen`, FK catálogo, `metadata_ia`).
- Usuarios: wizard modular detrás de `AGENDAMIENTO_IA_ASISTIDO`.
- Proveedores: confirmación de solicitud con oferta precargada (fase posterior).

## Non-goals
- No persistir consultas efímeras al asistente.
- No audio ni transcripciones en R2.
- No LLM externo obligatorio en v1.
- No cambiar webhooks MercadoPago ni ofertas secundarias en ejecución.

## Alcance
`mecanimovil-backend` (ordenes, servicios, personalizacion lectura), `mecanimovil-usuarios`, `mecanimovil-prov`.
