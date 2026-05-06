# Tareas

## 1. Modelado de datos (dataset ML)
- [x] 1.1 Crear modelo `EventoSaludVehiculo` con snapshot (marca/modelo/año/motor),
  métricas (`km_desde_ultimo_servicio`, `meses_desde_ultimo_servicio`,
  `vida_util_referencia_km`) y contexto (checklist, orden, viaje, metadata).
- [x] 1.2 Migración `0020_eventosaludvehiculo` con índices por (componente, tipo)
  y (marca, modelo).

## 2. HealthEngine — Estimación inteligente sin historial
- [x] 2.1 Cambiar `historial_desconocido` para usar `max(km_total % eta, eta * 0.5)`
  en lugar de `eta` fijo.
- [x] 2.2 Capturar eventos `NIVEL_CRITICO` automáticamente desde `HealthEngine`.
- [x] 2.3 Mensaje `mensaje_alerta` indica cuántos ciclos fueron estimados.
- [x] 2.4 Reporte incluye `ciclos_estimados` y `km_en_ciclo_actual`.

## 3. PredictorSalud (servicio scikit-learn)
- [x] 3.1 `INDUSTRY_PRIORS` con vida útil por componente (priors bootstrap).
- [x] 3.2 Bootstrap: `km/día` del usuario desde `ViajeRegistrado` (60 días)
  + factor clima (`WEAR_MATRIX`).
- [x] 3.3 Inferencia ML: cargar `MEDIA_ROOT/ml_models/{slug}.joblib` con cache.
- [x] 3.4 Similares: `EventoSaludVehiculo` agregado por marca/modelo/año±2.
- [x] 3.5 Cache de predicciones (30 min) e invalidación cuando cambia km/salud.

## 4. Captura automática de eventos
- [x] 4.1 `actualizar_salud_desde_checklist` → eventos `SERVICIO_REALIZADO`
  con km_desde_ultimo_servicio y meses_desde_ultimo_servicio.
- [x] 4.2 `procesar_post_viaje` → evento `VIAJE_KM` + invalida predicciones.
- [x] 4.3 Serializer de creación de vehículo → evento `REGISTRO_INICIAL`.
- [x] 4.4 `HealthEngine` → evento `NIVEL_CRITICO` (1 por día por componente).

## 5. Entrenamiento ML
- [x] 5.1 Management command `entrenar_modelos_salud` con `RandomForestRegressor`
  (n_estimators=80, max_depth=12) y `LabelEncoder` para marca/modelo/motor.
- [x] 5.2 Tarea Celery `entrenar_modelos_salud_async` (cola heavy, soft 1500s).
- [x] 5.3 Beat: `crontab(day_of_week=0, hour=6, minute=0)` semanal domingos.

## 6. Endpoint API
- [x] 6.1 `GET /api/vehiculos/health/vehicle/{id}/predicciones/` (con `?force=1`).
- [x] 6.2 Resumen: `total_componentes`, `componentes_criticos`, `componentes_atencion_30d`,
  `top_3_urgentes`.

## 7. Frontend (mecanimovil-usuarios)
- [x] 7.1 `vehicleHealthService.getVehiclePredictions(id, force)`.
- [x] 7.2 `SmartPredictionsCard` con badge urgencias, riesgo 30d y factor clima.
- [x] 7.3 Integración en `VehicleHealthScreen` con paralelo a la carga de salud.

## 8. Calidad
- [x] 8.1 Validar sintaxis Python de todos los archivos modificados (ast.parse).
- [x] 8.2 Sin lints en backend ni frontend.
- [x] 8.3 Spec actualizada con 4 nuevos scenarios.
