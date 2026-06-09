# vehiculos Specification (delta — checklist-inteligente-v2)

## MODIFIED Requirements

### Requirement: Predicciones inteligentes de mantenimiento (MODIFICADO)

El `PredictorSalud` **SHALL** ser consumido por `checklist_recommender.py` para
generar recomendaciones de mantenimiento basadas en el estado observado post-checklist.
Las predicciones ML generadas deben enriquecerse con el contexto del checklist
(componentes actualizados, km registrado, fecha del servicio).

#### Scenario: Recomendación ML basada en predicción de km restantes

- GIVEN un `ComponenteSaludVehiculo(slug='timing-belt', salud_porcentaje=45)`
  con `km_estimados_restantes=2500` calculado por `PredictorSalud`
- WHEN `generar_recomendaciones_checklist` procesa el checklist completado
- THEN se genera una recomendación con `prioridad=ATENCION` y `fuente=ML`
- AND `confianza` refleja la confianza del modelo para ese slug
- AND `servicios_sugeridos` contiene servicios de `ComponenteSalud.servicios_asociados`
  filtrados por `tipo_motor` del vehículo

## ADDED Requirements

### Requirement: Generación asíncrona de recomendaciones post-checklist

Al completarse un `ChecklistInstance` (estado `COMPLETADO`), el backend **SHALL**
encolar la tarea Celery `generar_recomendaciones_checklist` inmediatamente después
de `actualizar_salud_desde_checklist`. La tarea **SHALL** ejecutarse con fallback
síncrono si Celery no está disponible.

Las recomendaciones generadas **SHALL** cachearse en Redis con clave
`checklist_recomendaciones_{checklist_id}` y TTL de 86400 segundos (24h).

#### Scenario: Signal dispara generación de recomendaciones al completarse checklist

- GIVEN un `ChecklistInstance` que transiciona a `COMPLETADO` via `firmar-cliente`
  o `finalize` (con ambas firmas)
- WHEN `post_save(ChecklistInstance)` se dispara
- THEN se encola `actualizar_salud_desde_checklist.delay(checklist_id, vehicle_id)`
- AND se encola `generar_recomendaciones_checklist.delay(checklist_id)`
- AND ambas tareas son independientes (fallo en una no afecta a la otra)

#### Scenario: Cache previene recálculo en consultas repetidas

- GIVEN un checklist `COMPLETADO` cuyas recomendaciones ya fueron calculadas
- WHEN el cliente consulta `GET .../recomendaciones/` varias veces
- THEN solo se ejecuta `generar_recomendaciones_checklist` una vez
- AND las respuestas subsiguientes se sirven desde Redis hasta TTL 24h

### Requirement: Recomendaciones incluyen inferencia colaborativa

Cuando el `PredictorSalud` no tiene modelo entrenado (< 30 eventos) para un
componente, `checklist_recommender.py` **SHALL** usar la inferencia por similitud
de `predictor_salud.py` para generar recomendaciones `PROACTIVA` cuando al menos
10 vehículos similares (misma marca/modelo/año ± 2 años) tienen datos para ese
componente.

#### Scenario: Recomendación PROACTIVA por inferencia colaborativa sin modelo ML

- GIVEN un vehículo VW Polo 2018 con `timing-belt` al 55%
- AND `EventoSaludVehiculo` tiene 12 registros de vehículos similares que
  reemplazaron la correa entre 85.000–95.000 km
- AND el vehículo tiene 83.000 km actuales
- WHEN `generar_recomendaciones_checklist` corre para un checklist de ese vehículo
- THEN se genera una recomendación con `prioridad=PROACTIVA` y `fuente=COLABORATIVO`
- AND `razon` menciona cuántos vehículos similares y el rango de km observado
