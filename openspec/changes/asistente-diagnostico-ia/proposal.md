# asistente-diagnostico-ia

## Why

Los técnicos asignados a una orden muchas veces no conocen el procedimiento exacto de reparación ni tienen referencia de manual para el vehículo y problema reportado. Se requiere una guía de apoyo basada en IA usando los datos ya disponibles en la orden.

## What Changes

- Modelo `DiagnosticoAsistidoOrden` para cachear resultados por orden.
- Servicio `ordenes/services/asistente_diagnostico/` que llama a Gemini vía HTTP (patrón `motor_semantico.py`).
- Endpoint `GET/POST /ordenes/proveedor-ordenes/{id}/asistente-ia/` con permisos para taller, supervisor o mecánico asignado.
- Feature flag `ASISTENTE_DIAGNOSTICO_IA_ENABLED`.

## Scope (out)

- Análisis multimodal (imagen/audio) del prototipo `analizador_fallas.py`.
- Cotización automática de repuestos en la app (solo guía y referencia de manual).

## Requirements

- REQ-IA-GENERAR: POST asistente-ia SHALL generar guía con causas probables, procedimiento paso a paso y referencia de manual.
- REQ-IA-CACHE: GET asistente-ia SHALL devolver el último diagnóstico cacheado.
- REQ-IA-PERMISO: solo taller/supervisor o mecánico asignado a la orden SHALL acceder.
- REQ-IA-FALLBACK: si Gemini no está disponible, SHALL responder `disponible=false` sin error 500.
