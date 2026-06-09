# Design: Checklist Inteligente v2

## Context

El sistema de checklists ya tiene una arquitectura sólida de 4 capas (catalog → template → instance → response) con actualización de salud vía Celery al completarse. Este change es un refinamiento de "checklist-inteligente-salud" (archivado 2026-05-09) que ya implementó la FK explícita a `ComponenteSalud`.

## Goals

1. Eliminar el cuello de botella de creación item-por-item con herramienta bulk en Admin + REST
2. Corregir inconsistencia entre `preview-impacto` (first-wins) y `actualizar_salud_desde_checklist` (last-wins) + 3 bugs asociados
3. Generar recomendaciones ML post-checklist accesibles para técnico y cliente

## Non-goals

- Refactorizar `populate_checklists_por_servicio.py` (sigue siendo la fuente de verdad para deploy)
- Cambiar el modelo de datos (no migrations)
- Modificar el flujo de firma (ya correcto: técnico desde prov app, cliente desde usuarios app)
- Cambiar reglas de exclusión de PRECOMPRA/Diagnóstico (ya correcto via `tipo_intencion_default`)

## Decisions

### D1: Bulk Item Creation vía Admin Action + Endpoint REST

El `ChecklistItemTemplateInline` en `admin.py` solo muestra `orden_visual` y `catalog_item` (línea 177). Se añaden `tipo_actualizacion` y `componente_salud_asociado` al inline.

Para bulk: acción de admin en `ChecklistTemplateAdmin` + endpoint `POST .../bulk-add-items/`. El endpoint acepta `categoria + componente_ids + tipo_evaluacion` y genera en un solo request todos los `ChecklistItemTemplate` necesarios.

`tipo_evaluacion`:
- `rapida` → 1 ítem SELECT por componente (`tipo_actualizacion=INSPECCIONA`)
- `completa` → 1 ítem SELECT + 1 ítem COMPONENT_HEALTH por componente
- `reemplazo` → 1 ítem BOOLEAN por componente (`tipo_actualizacion=REEMPLAZA`)

Los ítems del catálogo se buscan por `(categoria, tipo_pregunta)`. Si no existen, se crean con `get_or_create`.

### D2: Smart Health Merge — Tabla de Prioridad

**Problema verificado en código**: `componentes_para_actualizar[comp_salud.id] = comp_salud` en `tasks.py:689` sobrescribe sin política. `preview-impacto` usa `ya_visto` (first-wins) en líneas 1070–1081.

**Solución**: Extraer función `_candidatos_por_componente(respuestas)` que retorna `{comp_id: mejor_respuesta}` usando la tabla:

```
PRIORIDAD_TIPO_ACTUALIZACION = {'REEMPLAZA': 0, 'INSPECCIONA': 1, 'INFORMATIVO': 99}
PRIORIDAD_TIPO_PREGUNTA = {'COMPONENT_HEALTH': 0, 'SELECT': 1, 'RATING': 2, 'NUMBER': 3, 'BOOLEAN': 4}
```

Ganador = mínima tupla `(prio_actualizacion, prio_pregunta, orden_visual)`. Tanto `actualizar_salud_desde_checklist` como `preview_impacto` usan esta función → comportamiento idéntico.

**Fix BOOLEAN REEMPLAZA**: antes de resetear salud, verificar `respuesta.respuesta_booleana is not False`. Si es `False`, tratar como INFORMATIVO.

**Expandir `SALUD_DESDE_SELECT`**: añadir entradas para variantes observadas en `populate_checklists_por_servicio.py`:
- `'Óptimo'` → 95.0
- `'Desgastadas'` → 30.0
- `'Nivel óptimo'` → 100.0
- `'Nivel bajo'` → 40.0
- `'Muy bajo'` → 15.0
- `'Requiere cambio'` → 25.0
- `'Requiere cambio urgente'` → 10.0
- `'Sin desgaste visible'` → 90.0
- `'Desgaste leve'` → 70.0
- `'Desgaste moderado'` → 50.0
- `'Desgaste severo'` → 20.0

### D3: ML Recommendations — Nuevo servicio `checklist_recommender.py`

Servicio independiente que consume:
- `ComponenteSaludVehiculo` (estado post-checklist)
- `EventoSaludVehiculo` (historial para anomalías)
- `PredictorSalud` (predicciones km/tiempo)
- `resolver_servicio_sugerido()` / `ordenar_servicios_asociados()` (servicio sugerido)

**3 capas de recomendaciones:**

1. **Anomalías determinísticas**: compara salud post-checklist vs. último evento `SERVICIO_REALIZADO`. Si la salud bajó ≥20pp en ≤60 días → `URGENTE`. Si bajó 10–20pp en ≤30 días → `ATENCION`.

2. **PredictorSalud ML**: para componentes con `nivel_alerta in ('URGENTE', 'CRITICO')` o `km_estimados_restantes < 5000`, llama `predecir_siguiente_mantenimiento(slug)`. Si `probabilidad_falla_30d > 0.3` → `URGENTE`. Si `km_hasta_critico < 3000` → `ATENCION`.

3. **Inferencia colaborativa**: para componentes no cubiertos en capas 1-2 con `nivel_alerta == 'ATENCION'`, llama `_inferencia_por_similares(slug, vehiculo)` de `predictor_salud.py`. Si `km_mediana_reemplazo - km_actual < 5000` → `PROACTIVA`.

**Cache Redis**: resultados en `checklist_recomendaciones_{checklist_id}` TTL 24h.

**Trigger**: `post_save(ChecklistInstance, COMPLETADO)` en `signals.py` añade `generar_recomendaciones_checklist.delay(checklist_id)` tras `actualizar_salud_desde_checklist`.

### D4: Frontend — Secciones de Resultado

**mecanimovil-prov** (`ChecklistCompletedView.tsx`):
- Llamada a `GET .../recomendaciones/` al montar
- Cards de prioridad con badge de color, razón, servicios sugeridos
- Sin CTA de agendamiento (es pantalla del técnico)

**mecanimovil-usuarios** (`ChecklistViewerModal.js`):
- Nueva sección "Recomendaciones del Taller" con scroll horizontal o accordion
- Cards: prioridad URGENTE=rojo, ATENCION=naranja, PROACTIVA=azul
- CTA "Agendar servicio" solo si `servicios_sugeridos.length > 0`
- Usa `navigateCrearSolicitudConServicio(servicioId)` existente en `homeScheduleNavigation`

## API

### `POST /api/checklists/templates/{id}/bulk-add-items/`

```
Request: {
  "categoria": "SISTEMA_FRENOS",
  "componente_ids": [1, 2, 3],
  "tipo_evaluacion": "completa" | "rapida" | "reemplazo"
}

Response 201: {
  "items_creados": 6,
  "items_existentes": 0,
  "items": [{id, orden_visual, catalog_item_nombre, tipo_actualizacion, componente_nombre}]
}
```

Permission: solo admins (`IsAdminUser`).

### `GET /api/checklists/instances/{id}/recomendaciones/`

```
Response 200: {
  "checklist_id": 42,
  "vehiculo_id": 7,
  "generado_en": "2026-06-09T14:30:00Z",
  "componentes_actualizados": [
    {"nombre": "Pastillas de Freno", "slug": "brakes", "salud_anterior": 75.0, "salud_nueva": 60.0, "tipo_actualizacion": "INSPECCIONA"}
  ],
  "recomendaciones": [
    {
      "prioridad": "URGENTE",
      "componente_slug": "brakes",
      "componente_nombre": "Pastillas de Freno",
      "razon": "Desgaste acelerado: bajó de 75% a 60% en 15 días (> 20pp en < 60 días)",
      "confianza": 0.95,
      "fuente": "ANOMALIA",
      "servicios_sugeridos": [{"id": 12, "nombre": "Cambio de Pastillas de Freno", "precio_referencia": 45000.0}]
    }
  ],
  "salud_general_antes": 73.0,
  "salud_general_despues": 68.0
}

Response 404: checklist no existe o no pertenece al usuario/proveedor
Response 400: checklist no está COMPLETADO
```

Permission: `IsAuthenticated` + (es proveedor de la orden OR es cliente dueño de la orden).

### ER Diagram (sin cambios de modelo)

```
ChecklistTemplate ──── ChecklistItemTemplate (campos health ahora expuestos en admin)
                              │
                              └─► ComponenteSalud ◄── ComponenteSaludVehiculo
                                                           │
                                                    EventoSaludVehiculo (ML)
                                                           │
                                               checklist_recommender.py (NUEVO)
                                                           │
                                            GET /recomendaciones/ endpoint (NUEVO)
```

## Migrations

Ninguna — todo el cambio es:
- Lógica en `tasks.py` (correcciones)
- Nuevo archivo `checklist_recommender.py`
- Nuevos endpoints en `views.py`
- Cambios en `admin.py`
- Cambios en serializers
- Cambios en frontend

## Risks

| Riesgo | Mitigación |
|--------|-----------|
| Cambiar la lógica de `actualizar_salud_desde_checklist` puede romper checklists históricos | La nueva lógica es más conservadora; `procesar_checklists_historicos` puede reejecutarse |
| `PredictorSalud` puede lanzar excepciones si no hay modelo entrenado | Capturar todas las excepciones por capa; recomendaciones de capas fallidas se omiten |
| Cache Redis TTL 24h puede servir recomendaciones desactualizadas | Invalidar cache explícitamente al reejecutar checklist (no aplica: checklist es inmutable post-COMPLETADO) |
| bulk-add-items puede crear duplicados si se llama 2 veces | Usar `get_or_create` por `(checklist_template, catalog_item)` |
