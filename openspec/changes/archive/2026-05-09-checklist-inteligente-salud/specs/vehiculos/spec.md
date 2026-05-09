# vehiculos Specification (delta)

## MODIFIED Requirements

### Requirement: Predicciones inteligentes de mantenimiento

El sistema **SHALL** entregar proyecciones por componente basadas en kilometraje, uso real del usuario, clima y aprendizaje colaborativo entre vehículos similares.

La predicción combina tres capas, en orden de prioridad:
1. **Bootstrap** — siempre disponible: km/día calculado desde `ViajeRegistrado`
   de los últimos 60 días, aritmética sobre la regla Weibull aplicada y multiplicador
   climático (`WEAR_MATRIX`).
2. **Modelo scikit-learn** — `RandomForestRegressor` por componente entrenado con
   `EventoSaludVehiculo` (eventos `SERVICIO_REALIZADO` + `INSPECCION_DECLARADA`
   + `NIVEL_CRITICO`). Solo se activa cuando un componente acumula ≥ 30 muestras.
3. **Similares** — estadísticas de vehículos con misma marca/modelo y año ± 2,
   provenientes del mismo dataset.

#### Scenario: Obtener predicciones para un vehículo
- GIVEN un usuario_final autenticado con un vehículo
- WHEN hace GET /api/vehiculos/health/vehicle/{id}/predicciones/
- THEN recibe una lista de predicciones por componente con
  `salud_actual`, `km_hasta_servicio`, `dias_hasta_atencion`,
  `probabilidad_falla_30/60/90`, `factor_clima`, `confianza`, `modelo_usado`
  y `recomendacion` legible.

#### Scenario: Captura automática de eventos para entrenamiento
- GIVEN un proveedor completa un checklist con servicios realizados
- WHEN se ejecuta `actualizar_salud_desde_checklist`
- THEN se crea un `EventoSaludVehiculo` con `tipo_evento=SERVICIO_REALIZADO`
  por cada ítem con `tipo_actualizacion='REEMPLAZA'`
- AND se crea un `EventoSaludVehiculo` con `tipo_evento=INSPECCION_DECLARADA`
  por cada ítem con `tipo_actualizacion='INSPECCIONA'` y `salud_porcentaje`
  igual al valor declarado por el técnico
- AND ambos eventos incluyen los campos snapshot (marca, modelo, año, motor, km,
  km_desde_ultimo_servicio, meses_desde_ultimo_servicio) usados como features
  para entrenamiento ML.

#### Scenario: Re-entrenamiento periódico de modelos
- GIVEN existen ≥ 30 eventos para un componente en `EventoSaludVehiculo`
- WHEN se dispara `entrenar_modelos_salud_async` (semanal, domingo 06:00 UTC)
- THEN se entrena un `RandomForestRegressor` por componente y se persiste como
  `MEDIA_ROOT/ml_models/{slug}.joblib` para que `PredictorSalud` lo cargue.

## ADDED Requirements

### Requirement: Anclaje Weibull desde inspección declarada

El `HealthEngine` **SHALL** anclar la curva Weibull cuando una respuesta de checklist con `tipo_actualizacion='INSPECCIONA'` fija un porcentaje de vida útil para un componente: persiste `ComponenteSaludVehiculo.salud_anclada_pct` y deriva un km base efectivo para que recálculos posteriores decaigan desde ese ancla en lugar de desde el km del último servicio.

#### Scenario: Técnico declara aceite al 35%, vehículo se mueve 1000 km

- GIVEN un componente `Aceite Motor` con `vida_util_proyectada=10000`,
  `salud_anclada_pct=35.0`, `historial_fuente='CHECKLIST'`
- AND un vehículo con `kilometraje=85000` al momento de la inspección
- WHEN el vehículo recorre 1000 km adicionales y `HealthEngine` recalcula
- THEN `salud_porcentaje` < 35.0 (decae monotónicamente)
- AND `salud_anclada_pct` permanece en 35.0 (no se sobrescribe)

#### Scenario: Reemplazo posterior limpia el ancla

- GIVEN un componente con `salud_anclada_pct=70.0`, `historial_fuente='CHECKLIST'`
- WHEN otro checklist con `tipo_actualizacion='REEMPLAZA'` se completa
- THEN `salud_porcentaje=100.0`
- AND `salud_anclada_pct=null`
- AND `historial_fuente='CHECKLIST'`
