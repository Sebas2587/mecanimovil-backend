# Tasks: Checklist Inteligente v2

## 1. OpenSpec Artifacts
- [x] Crear `.openspec.yaml`
- [x] Crear `proposal.md`
- [x] Crear `design.md`
- [x] Crear `specs/checklists/spec.md` (delta)
- [x] Crear `specs/vehiculos/spec.md` (delta)

## 2. Backend — Bulk Item Creation

- [ ] Exponer `tipo_actualizacion` y `componente_salud_asociado` en `ChecklistItemTemplateInline` en `admin.py`
- [ ] Crear `BulkAddItemsForm` en `admin.py` con campos `categoria`, `componente_ids`, `tipo_evaluacion`
- [ ] Añadir acción `bulk_add_items_desde_catalogo` en `ChecklistTemplateAdmin`
- [ ] Añadir `@action bulk_add_items` (POST) en `ChecklistTemplateViewSet` en `views.py`
- [ ] Añadir serializer `BulkAddItemsSerializer` en `serializers.py`

## 3. Backend — Smart Health Merge

- [ ] Extraer `_candidatos_por_componente(respuestas)` en `tasks.py` con tabla de prioridad
- [ ] Refactorizar `actualizar_salud_desde_checklist` para usar `_candidatos_por_componente`
- [ ] Refactorizar `preview_impacto` en `views.py` para usar `_candidatos_por_componente` importada desde `tasks.py`
- [ ] Fix BOOLEAN REEMPLAZA: verificar `respuesta_booleana is not False` antes de resetear salud
- [ ] Expandir `SALUD_DESDE_SELECT` con variantes en uso (`Óptimo`, `Desgastadas`, etc.)

## 4. Backend — ML Recommender Service

- [ ] Crear `mecanimovilapp/apps/vehiculos/services/checklist_recommender.py`
  - [ ] Capa 1: anomalías determinísticas (desgaste acelerado vs. último `EventoSaludVehiculo`)
  - [ ] Capa 2: PredictorSalud ML (predicción km/probabilidad falla)
  - [ ] Capa 3: inferencia colaborativa (vehículos similares)
  - [ ] Resolver servicios sugeridos con `ordenar_servicios_asociados()`
  - [ ] Cache Redis `checklist_recomendaciones_{id}` TTL 24h
- [ ] Añadir tarea Celery `generar_recomendaciones_checklist` en `tasks.py`
- [ ] Añadir trigger en `signals.py` de checklists: encolar `generar_recomendaciones_checklist.delay(checklist_id)` cuando `COMPLETADO`

## 5. Backend — Endpoint Recomendaciones

- [ ] Añadir `@action recomendaciones` (GET) en `ChecklistInstanceViewSet` en `views.py`
- [ ] Añadir `RecomendacionChecklistSerializer` en `serializers.py`
- [ ] Validar permisos: proveedor de la orden OR cliente dueño

## 6. Frontend — mecanimovil-prov

- [ ] Añadir `getRecomendaciones(instanceId)` en `services/checklistService.ts`
- [ ] Añadir tipo `ChecklistRecomendacion` y `ChecklistRecomendacionesResponse` en `checklistService.ts`
- [ ] Añadir sección "Recomendaciones para el cliente" en `components/checklist/ChecklistCompletedView.tsx`

## 7. Frontend — mecanimovil-usuarios

- [ ] Añadir `obtenerRecomendacionesChecklist(instanceId)` en `app/services/checklistService.js`
- [ ] Añadir sección "Recomendaciones del Taller" en `app/components/modals/ChecklistViewerModal.js`
- [ ] Implementar cards de prioridad con CTA "Agendar servicio"

## 8. Calidad y Cierre

- [ ] Ejecutar `openspec validate checklist-inteligente-v2 --strict`
- [ ] Ejecutar `openspec archive checklist-inteligente-v2`
