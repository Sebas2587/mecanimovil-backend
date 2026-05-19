# Propuesta: Fase 5 — Comprensión semántica (sin APIs de pago)

## Why
El motor léxico v1 no basta para lenguaje coloquial. No hay presupuesto para OpenAI/Anthropic.

## What Changes
- **Por defecto:** `AGENDAMIENTO_IA_SEMANTICO_PROVEEDOR=lexico` — léxico + fuzzy local, **cero API de pago**.
- **Aprendizaje acumulativo:** modelo `PatronAprendizajeNecesidad` alimentado al confirmar solicitudes (fragmentos normalizados, sin texto crudo de consultas efímeras).
- **Cruce salud ↔ texto:** lectura de métricas de salud del vehículo, interpretación y alertas si el desgaste no coincide con lo que describe el usuario.
- **Opcional gratuito:** Gemini / Hugging Face / Ollama con fallback a léxico local.
- Campos API: `resumen_salud`, `alertas_cruce`, `patrones_aprendizaje_en_sistema`.

## Non-goals
- OpenAI, Anthropic u otros proveedores de pago.
- Chat multi-turn en servidor.

## Alcance
`mecanimovil-backend` — `motor_semantico.py`, settings, Render.
