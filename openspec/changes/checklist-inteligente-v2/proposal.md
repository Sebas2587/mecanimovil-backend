# Checklist Inteligente v2 — Bulk Creation, Smart Health Merge y Recomendaciones ML

## Why

El sistema de checklists tiene tres problemas principales que frenan la eficiencia operativa del sistema:

### 1. Cuello de botella en la creación de templates

`populate_checklists_por_servicio.py` tiene 1229 líneas y define cada `ChecklistItemTemplate` de forma individual. En Django Admin, el `ChecklistItemTemplateInline` solo muestra `orden_visual` y `catalog_item`, ocultando los campos de salud (`tipo_actualizacion`, `componente_salud_asociado`). Para un servicio con 100+ items de evaluación (ej. diagnóstico multisistema), crear o actualizar cada item es un proceso manual imposible de escalar.

### 2. Inconsistencia en la actualización de salud (last-wins)

`actualizar_salud_desde_checklist` en `tasks.py` itera respuestas y acumula en un dict `{comp_id: data}` sin política de resolución explícita: el último ítem en iterar gana sobre el mismo `ComponenteSalud`. Los tres bugs concretos son:
- Un ítem `BOOLEAN` de tipo `REEMPLAZA` con respuesta `False` aún dispara reset a 100%
- `SALUD_DESDE_SELECT` no reconoce opciones en uso como `"Óptimo"`, `"Desgastadas"`, `"Requiere cambio urgente"` → retorna `None` → la inspección se descarta silenciosamente
- `preview-impacto` (first-wins) y `actualizar_salud_desde_checklist` (last-wins) pueden producir diffs distintos para el mismo conjunto de respuestas

### 3. No existen recomendaciones post-servicio para el cliente

Después de que el checklist es completado (técnico + cliente firman), el sistema actualiza métricas de salud pero no genera recomendaciones de servicios o mantenimientos derivadas del estado observado. El técnico ya tiene el `PredictorSalud` con 3 capas de ML disponible, pero nunca se expone al cliente en el contexto del checklist.

## What Changes

1. **Bulk Item Creation (Admin + REST)** — Nueva acción en `ChecklistTemplateAdmin` y endpoint `POST /api/checklists/templates/{id}/bulk-add-items/` que acepta `categoria + componente_ids[] + tipo_evaluacion` y genera en un solo request todos los `ChecklistItemTemplate` con `tipo_actualizacion` y `componente_salud_asociado` pre-cableados. El `ChecklistItemTemplateInline` expone los campos de salud.

2. **Smart Health Merge** — `actualizar_salud_desde_checklist` adopta una política de prioridad explícita: `REEMPLAZA` > `COMPONENT_HEALTH` > `SELECT` > `RATING`. Solo el candidato con mejor score por `ComponenteSalud.id` se aplica. Se corrigen los tres bugs. La misma lógica se reutiliza en `preview-impacto` eliminando la discrepancia.

3. **ML Recommendations Post-Checklist** — Nuevo servicio `checklist_recommender.py` con 3 capas: anomalías determinísticas, `PredictorSalud` ML y inferencia colaborativa por vehículos similares. Los resultados se exponen en `GET /api/checklists/instances/{id}/recomendaciones/` (accesible para proveedor y cliente), se cachean en Redis TTL 24h, y se generan asincrónicamente via Celery al mismo tiempo que `actualizar_salud_desde_checklist`.

4. **Frontend Provider** — `ChecklistCompletedView.tsx` añade sección "Recomendaciones para el cliente" con cards de prioridad.

5. **Frontend Cliente** — `ChecklistViewerModal.js` añade sección "Recomendaciones del Taller" con CTA "Agendar servicio" que navega a crear solicitud con el servicio sugerido.

## Impact

- **Affected specs:**
  - `openspec/specs/checklists/spec.md` (ADDED: bulk creation, recomendaciones endpoint, smart merge)
  - `openspec/specs/vehiculos/spec.md` (MODIFIED: recomendaciones ML post-checklist)
- **Affected code:**
  - Backend: `apps/checklists/views.py`, `apps/checklists/admin.py`, `apps/checklists/serializers.py`, `apps/vehiculos/tasks.py`, `apps/vehiculos/services/checklist_recommender.py` (NUEVO)
  - Frontend prov: `services/checklistService.ts`, `components/checklist/ChecklistCompletedView.tsx`
  - Frontend usuarios: `app/services/checklistService.js`, `app/components/modals/ChecklistViewerModal.js`
- **No migrations required** — ningún modelo nuevo; solo nueva lógica de servicio y endpoints
- **Backward compatible** — items individuales siguen funcionando; bulk es aditivo
