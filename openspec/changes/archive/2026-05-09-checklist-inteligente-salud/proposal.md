# Checklist inteligente con actualización contextual de salud

## Why

Hoy `actualizar_salud_desde_checklist` ([apps/vehiculos/tasks.py](mecanimovilapp/apps/vehiculos/tasks.py)) trata cualquier
checklist completado como si reemplazara los componentes asociados: fuerza
`salud_porcentaje = 100.0` y `nivel_alerta = 'OPTIMO'` mediante un dict
`mapeo_componentes` hardcoded por substring del nombre del ítem. Como
consecuencia:

- Un servicio de **diagnóstico/inspección** (`Diagnóstico mecánico`,
  `Revisión técnica`, `Servicio escáner automotriz`) infla todos los
  componentes a 100% en lugar de capturar el estado real declarado por el
  técnico.
- El `bulk_update` no incluye `historial_fuente`, por lo que el cap de
  confianza definido en `HealthEngine.SALUD_MAX_POR_FUENTE`
  ([services/health_engine.py](mecanimovilapp/apps/vehiculos/services/health_engine.py))
  no se aplica nunca a los datos provenientes de checklists.
- El `mapeo_componentes` por substring es frágil: cualquier cambio en el
  nombre de un ítem del catálogo rompe silenciosamente el matching.
- El proveedor que llena el checklist no tiene visibilidad del estado actual
  del componente que está actualizando, ni el sistema le muestra el impacto
  antes de finalizar.

## What Changes

1. **Modelo: granularidad por ítem** — `ChecklistTemplate.tipo_intencion_default`
   (`REPARACION` | `INSPECCION` | `PRECOMPRA` | `MIXTO`) y, sobre cada
   `ChecklistItemTemplate`, los campos `tipo_actualizacion`
   (`REEMPLAZA` | `INSPECCIONA` | `INFORMATIVO`) y
   `componente_salud_asociado` (FK a `ComponenteSalud`).
2. **Catálogo: nuevo input `COMPONENT_HEALTH`** — slider 0–100 para que el
   técnico declare la vida útil restante por componente durante una
   inspección. Reuso de `SELECT` con tabla de mapeo categórico
   (`Excelente=95`, `Bueno=80`, `Regular=60`, `Malo=35`, `Crítico=15`).
3. **Health: ancla Weibull** — `ComponenteSaludVehiculo.salud_anclada_pct`
   guarda el valor declarado para que `HealthEngine` proyecte la curva desde
   ese punto en cada recálculo posterior.
4. **Refactor task** — `actualizar_salud_desde_checklist` (y
   `procesar_checklists_historicos_vehiculo`) reemplazan el
   `mapeo_componentes` hardcoded por la FK explícita y ramifican por
   `tipo_actualizacion`. Se setea `historial_fuente='CHECKLIST'` en
   `bulk_update`.
5. **Endpoints nuevos** — `GET /api/checklists/instances/{id}/salud-snapshot/`
   y `POST /api/checklists/instances/{id}/preview-impacto/`.
6. **Frontend proveedor (mecanimovil-prov)** — slider `COMPONENT_HEALTH`,
   header con la salud actual sobre cada ítem y modal `ChecklistDiffModal`
   antes de finalizar.
7. **Frontend usuario (mecanimovil-usuarios)** — badges diferenciados
   "Verificado por taller" vs "Estimado" en `VehicleHealthScreen`/
   `VehicleHealthCard`.
8. **Deploy en Render** — `populate_checklists_por_servicio` se ejecuta en
   cada build (idempotente) para mantener templates alineados con el catálogo
   de servicios.
9. **Eventos ML** — nuevo `tipo_evento='INSPECCION_DECLARADA'` en
   `EventoSaludVehiculo` para que `PredictorSalud` aprenda también de
   inspecciones (no solo de reemplazos).

## Impact

- **Affected specs**:
  - `openspec/specs/checklists/spec.md` (ADDED — nuevo spec dedicado al
    dominio).
  - `openspec/specs/vehiculos/spec.md` (MODIFIED — sección "Captura
    automática de eventos para entrenamiento").
- **Affected code**:
  - Backend:
    `mecanimovilapp/apps/checklists/{models,serializers,views,urls,signals}.py`,
    nueva migración `0004_*`, nueva migración en `vehiculos`,
    `mecanimovilapp/apps/vehiculos/{tasks.py,services/health_engine.py,models_health.py}`,
    `mecanimovilapp/apps/checklists/management/commands/populate_checklists_por_servicio.py`,
    `build.sh`.
  - Frontend (mecanimovil-prov):
    `services/checklistService.ts`, `components/checklist/ChecklistItemRenderer.tsx`,
    `components/checklist/ChecklistContainer.tsx`,
    nuevo `components/checklist/ChecklistDiffModal.tsx`.
  - Frontend (mecanimovil-usuarios):
    `app/components/vehicles/VehicleHealthCard.js`,
    `app/screens/vehicles/VehicleHealthScreen.js`,
    `app/services/vehicleHealthService.js`.
