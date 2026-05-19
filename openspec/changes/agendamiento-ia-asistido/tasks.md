# Tareas

## Fase 0
- [x] OpenSpec change (backend, usuarios, prov)

## Fase 1 — Backend
- [x] Migración `origen`, `oferta_servicio`, `metadata_ia`
- [x] Servicios `motor_necesidad`, `motor_match`
- [x] ViewSet `AsistenteAgendamientoViewSet` + URLs
- [x] Flag `AGENDAMIENTO_IA_ASISTIDO`
- [x] Tests `test_asistente_agendamiento.py`
- [x] `motor_confirmacion` + `confirmar-candidato`

## Fase 2 — Usuarios (repo usuarios)
- [x] Flujo comparador catálogo + confirmar-candidato
- [x] STT on-device

## Fase 3 — Proveedores (repo prov)
- [x] UI confirmación catálogo en solicitud-detalle

## Fase 5 — Comprensión semántica (gratuita)
- [x] `motor_semantico.py` — proveedor `lexico` local + gemini/hf/ollama opcionales
- [x] Sin OpenAI/Anthropic; Render con `SEMANTICO_PROVEEDOR=lexico`
- [x] OpenSpec `openspec/changes/agendamiento-ia-fase5-semantica/`

## Fase 4 — Cierre ciclo catálogo
- [x] Cliente: aceptar fecha alternativa (`aceptar-fecha-catalogo`)
- [x] Cliente: detalle/listas estado `pendiente_confirmacion`
- [x] Proveedor: modal proponer fecha
- [x] Expiración catálogo sin confirmación + cancelación cliente
- [x] Proveedor ve solicitudes `pendiente_confirmacion` en listado

## Fase 6 — Integración aprendizaje
- [x] metadata_ia_entrada en confirmar-candidato
- [x] Comando `alimentar_patrones_necesidad`

## Fase 7 — UX comparador + operación
- [x] Comparador catálogo 1+ candidatos con contexto IA
- [x] GET `resumen-operacion` (staff)

## Catálogo geolocalizado (flujo principal)
- [x] Matching candidatos por distancia (lat/lng)
- [x] Wizard: servicio → repuestos → ubicación → fecha → comparador
- [ ] Chat / APIs conversacionales IA (backlog)

