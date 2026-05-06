# Predicciones ML de salud vehicular

## Why

Hoy, el `HealthEngine` calcula salud por Weibull (km + tiempo) y muestra ~37 % fijo
para vehículos sin historial — sin diferenciar por tipo de componente. El usuario
no recibe información predictiva concreta ("¿en cuántos km / días debo cambiar X?")
ni se aprovecha el dataset que se está acumulando con cada checklist completado.

## What Changes

1. **Tabla `EventoSaludVehiculo`** — captura eventos relevantes (servicio,
   nivel crítico, viaje, registro inicial) con snapshot del vehículo. Es la fuente
   de verdad para entrenamiento ML.
2. **`HealthEngine.calcular_salud_vehiculo`** — modo "historial desconocido" mejorado:
   `km_recorridos = max(km_total % eta, eta * 0.5)` por componente.
3. **`PredictorSalud`** (nuevo servicio) — pipeline en 3 capas:
   - Bootstrap (km/día del usuario + clima + Weibull) — siempre activo.
   - scikit-learn (`RandomForestRegressor` por componente) — cuando hay ≥ 30 eventos.
   - Similares (estadísticas vehículos similares) — refuerzo colaborativo.
4. **Endpoint** `GET /api/vehiculos/health/vehicle/{id}/predicciones/` — expone
   resultado al frontend con resumen ejecutivo.
5. **Management command** `entrenar_modelos_salud` + tarea Celery semanal
   (Domingos 06:00 UTC) que reentrena con eventos acumulados.
6. **Frontend** — `SmartPredictionsCard` en `VehicleHealthScreen` con
   próxima mantención, riesgo a 30 d y factor climático por componente.

## Impact

- **Affected specs**: `openspec/specs/vehiculos/spec.md` — agrega requirements de
  predicciones ML, captura automática de eventos y estimación por ciclo.
- **Affected code**:
  - Backend: `models_health.py`, `health_engine.py`, `tasks.py`, `views_health.py`,
    `serializers.py`, nueva migración 0020, `services/predictor_salud.py`,
    `management/commands/entrenar_modelos_salud.py`, `celery.py`.
  - Frontend: `services/vehicleHealthService.js`,
    `components/vehicles/SmartPredictionsCard.js`, `screens/vehicles/VehicleHealthScreen.js`.
