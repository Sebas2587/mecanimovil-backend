# vehiculos Specification

## Purpose
Gestión de vehículos registrados por el usuario. Un vehículo es requisito previo
para crear solicitudes de servicio.

## Requirements

### Requirement: CRUD de vehículos del usuario
El usuario puede registrar, editar y eliminar sus vehículos.

#### Scenario: Registrar vehículo
- GIVEN un usuario_final autenticado
- WHEN hace POST /api/vehiculos/ con marca, modelo, año, patente
- THEN el vehículo queda asociado al usuario
- AND puede usarse en nuevas solicitudes de servicio

#### Scenario: Patente duplicada
- GIVEN un vehículo ya registrado con una patente
- WHEN otro usuario intenta registrar la misma patente
- THEN recibe status 400 con mensaje "Patente ya registrada"

#### Scenario: Eliminar vehículo con órdenes activas
- GIVEN un vehículo asociado a una orden en estado=en_progreso
- WHEN el usuario intenta eliminarlo
- THEN recibe status 400 con mensaje "No puedes eliminar un vehículo con órdenes activas"

### Requirement: Historial de servicios por vehículo
El usuario puede ver el historial de órdenes completadas por vehículo.

#### Scenario: Ver historial de un vehículo
- GIVEN un vehículo con órdenes completadas
- WHEN el usuario hace GET /api/vehiculos/{id}/historial/
- THEN recibe la lista de órdenes completadas con fecha, servicio y proveedor

### Requirement: Predicciones inteligentes de mantenimiento
El sistema entrega proyecciones por componente basadas en kilometraje, uso real
del usuario, clima y aprendizaje colaborativo entre vehículos similares.

La predicción combina tres capas, en orden de prioridad:
1. **Bootstrap** — siempre disponible: km/día calculado desde `ViajeRegistrado`
   de los últimos 60 días, aritmética sobre la regla Weibull aplicada y multiplicador
   climático (`WEAR_MATRIX`).
2. **Modelo scikit-learn** — `RandomForestRegressor` por componente entrenado con
   `EventoSaludVehiculo` (eventos `SERVICIO_REALIZADO` + `NIVEL_CRITICO`). Solo se
   activa cuando un componente acumula ≥ 30 muestras.
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
  y los campos snapshot (marca, modelo, año, motor, km, km_desde_ultimo_servicio,
  meses_desde_ultimo_servicio) usados como features para entrenamiento ML.

#### Scenario: Re-entrenamiento periódico de modelos
- GIVEN existen ≥ 30 eventos para un componente en `EventoSaludVehiculo`
- WHEN se dispara `entrenar_modelos_salud_async` (semanal, domingo 06:00 UTC)
- THEN se entrena un `RandomForestRegressor` por componente y se persiste como
  `MEDIA_ROOT/ml_models/{slug}.joblib` para que `PredictorSalud` lo cargue.

### Requirement: Estimación inteligente sin historial
Para vehículos sin historial de servicios registrados, la salud por componente
NO puede ser un valor fijo de ~37 % universal. Cada componente tiene una vida
útil distinta y debe estimarse según el ciclo en que se encuentra.

#### Scenario: Vehículo de 150.000 km sin historial
- GIVEN un vehículo con kilometraje 150.000 km y `historial_conocido=False`
  para todos sus componentes
- WHEN el HealthEngine recalcula la salud
- THEN cada componente recibe un valor estimado basado en
  `km_recorridos_efectivos = max(km_total % eta, eta * 0.5)`,
  produciendo valores diferenciados (ej. aceite ≈ 60 %, distribución ≈ 61 %,
  neumáticos ≈ 47 %) en lugar de un 37 % fijo
- AND el `mensaje_alerta` indica cuántos ciclos previos fueron estimados
