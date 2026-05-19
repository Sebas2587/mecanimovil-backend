# Tareas — Fase 5 semántica (gratuita)

## Backend
- [x] Motor local `lexico` (léxico + fuzzy, sin API)
- [x] Proveedores opcionales gratuitos: gemini, huggingface, ollama
- [x] Fallback automático a léxico local
- [x] Settings / Render / `.env.example` sin OpenAI
- [x] Tests

## Operaciones (solo si quieren más calidad que el motor local)
- [ ] Opción A: dejar `AGENDAMIENTO_IA_SEMANTICO_PROVEEDOR=lexico` (recomendado, sin keys)
- [ ] Opción B: `GEMINI_API_KEY` gratis en [Google AI Studio](https://aistudio.google.com/apikey) + `PROVEEDOR=auto`
