# asistente-diagnostico-cita-personal

## Why

Los técnicos asignados a citas personales de agenda necesitan la misma guía de reparación IA que en órdenes Mecanimovil, usando marca/modelo/año/cilindraje y descripción del servicio capturados en `CitaAgendaPersonalDetalle`.

## What Changes

- Modelo `DiagnosticoAsistidoCitaPersonal` (migración `0020`).
- `generar_guia_reparacion_cita_personal()` en `ordenes/services/asistente_diagnostico/`.
- Endpoint `GET/POST /ordenes/citas-agenda-personal/{id}/asistente-ia/` con permisos alineados al scoping de citas (taller/supervisor/mecánico asignado).

## Non-goals

- Multimodal (imagen/audio).
- Asistente en citas canceladas/cerradas desde UI (solo citas activas).

## Requirements

- REQ-IA-CITA-GENERAR: POST asistente-ia SHALL generar guía con el mismo esquema JSON que órdenes.
- REQ-IA-CITA-CACHE: GET asistente-ia SHALL devolver el último diagnóstico cacheado de la cita.
- REQ-IA-CITA-PERMISO: solo usuarios con acceso a la cita en `get_queryset` SHALL usar el endpoint.
- REQ-IA-CITA-FALLBACK: si Gemini no está disponible, SHALL responder `disponible=false` sin error 500.
