# Propuesta: Catálogo geolocalizado (flujo principal)

## Why
El valor inmediato para el cliente es elegir servicio y repuestos, ubicar el trabajo, comparar ofertas de catálogo por zona y confirmar al proveedor — sin chat ni LLM conversacional en esta etapa.

## What Changes
- Matching de candidatos con distancia cuando hay lat/lng.
- Wizard IA: vehículo + servicio → repuestos/urgencia → ubicación → fecha → comparador.
- Descripción opcional (fallback al confirmar).

## Deferred (fase futura)
- Chat cliente–proveedor en flujo catálogo.
- APIs conversacionales oficiales (OpenAI/Gemini) para asistencia por mensajes.

## Non-goals
- Reemplazar solicitud abierta a múltiples proveedores.
- Persistir consultas efímeras de análisis.
