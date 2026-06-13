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

### Requirement: Predicción climática de desgaste al conducir
El endpoint `GET /api/vehiculos/weather-prediction/` entrega riesgo de desgaste
por condición meteorológica. Si se envía `vehicle_id`, la respuesta **SHALL**
enriquecer cada grupo (`frenos`, `neumaticos`, `bateria`, `refrigerante`) con
datos de `ComponenteSaludVehiculo` coherentes con el motor de salud.

#### Scenario: Salud mostrada alinea con componentes reales
- GIVEN un vehículo con pastillas y discos en estado óptimo (salud alta)
- WHEN se consulta la predicción con `vehicle_id` válido
- THEN el agregado «frenos» usa solo slugs de fricción (p. ej. `brakes`,
  `brake-discs`, alias `pastillas-freno` / `discos-freno`) y **excluye**
  fluidos o embrague (`brake-fluid`, `liquido-frenos`, etc.)
- AND `salud_actual` en cada componente del JSON refleja el promedio de salud
  de los registros agrupados (no un componente ajeno al grupo)

#### Scenario: Riesgo de conducción no contradice la salud del motor
- GIVEN telemetría enriquecida con `salud_porcentaje` del motor de salud
- WHEN se calcula `driving_risk` para un grupo
- THEN el desgaste base es `(100 - salud_porcentaje)` acotado a 0–100,
  multiplicado por el coeficiente climático (`WEAR_MATRIX`)
- AND **no** se mezcla en ese cálculo `km_estimados_restantes` /
  `vida_util_proyectada` (evita duplicar señal y marcar riesgo ~100 % con salud óptima)

### Requirement: Motor de salud vehicular (HealthEngine)

El sistema **SHALL** calcular la salud de cada componente mediante `HealthEngine`
(`vehiculos/services/health_engine.py`), aplicando reglas Weibull por km y tiempo,
caps de conducción, antigüedad del componente y fuente del historial.

Tras completar un checklist, `actualizar_salud_desde_checklist` escribe anclas
(`REEMPLAZA` → 100 %; `INSPECCIONA` → `salud_anclada_pct`) y encola
`calcular_salud_vehiculo_async`, que **recalcula** y persiste el estado final.

#### Scenario: Cálculo Weibull doble eje
- GIVEN un componente con regla `vida_util_km=eta`, `intervalo_meses=T`, `beta`
- WHEN `HealthEngine.calcular_salud_vehiculo` procesa el componente
- THEN `salud_km = exp(-(km_recorridos/eta)^beta) × 100`
- AND si `intervalo_meses` está definido,
  `salud_tiempo = exp(-(meses_desde_servicio/T)^beta) × 100`
- AND `salud_porcentaje = min(salud_km, salud_tiempo)` antes de caps adicionales

#### Scenario: Cap por antigüedad del componente (no del vehículo)
- GIVEN un slug en `_AGE_HARD_CAPS` (ej. `brake-fluid`: óptimo 2 años, crítico 4 años)
- AND `historial_conocido=True` con `fecha_ultimo_servicio` reciente (< 2 años)
- WHEN el vehículo tiene 13 años de antigüedad de fabricación
- THEN el cap por edad **SHALL NOT** forzar salud ≤ 20 % por la edad del vehículo
- AND la edad medida **SHALL** ser `(now - fecha_ultimo_servicio)` en años

#### Scenario: Cap conservador sin historial confirmado
- GIVEN un componente en `_AGE_HARD_CAPS` con `historial_conocido=False`
- AND un vehículo cuya antigüedad supera el límite crítico del componente
- WHEN `HealthEngine` recalcula
- THEN `salud_porcentaje` **SHALL** estar capada según `_AGE_HARD_CAPS`
  usando la antigüedad del vehículo como estimación conservadora

#### Scenario: Umbrales de nivel de alerta unificados
- GIVEN cualquier fuente que asigne `nivel_alerta` (HealthEngine o tasks post-checklist)
- THEN los umbrales **SHALL** ser: ≥70 % OPTIMO, ≥40 % ATENCION, ≥10 % URGENTE, <10 % CRITICO

#### Scenario: Pipeline Celery post-checklist
- GIVEN un `ChecklistInstance` en estado `COMPLETADO`
- WHEN se dispara `post_save` en checklists
- THEN se encola `actualizar_salud_desde_checklist` (cola `default`)
- AND luego `calcular_salud_vehiculo_async(force_recalculate=True)` (cola `default`)
- AND el worker Render consume colas `default,heavy`

### Requirement: Calidad de eventos ML para entrenamiento

`EventoSaludVehiculo` con `tipo_evento=SERVICIO_REALIZADO` **SHALL** incluir
`km_desde_ultimo_servicio > 0` solo cuando el componente tenía ancla previa
confirmada antes del servicio. El primer servicio que establece ancla **SHALL**
registrar `km_desde_ultimo_servicio=null` para no contaminar el dataset scikit-learn.

#### Scenario: Primer servicio establece ancla sin medir intervalo
- GIVEN un componente sin historial real previo al checklist
- WHEN se completa `REEMPLAZA` en checklist
- THEN el evento ML tiene `metadata.primer_ancla=true` y `km_desde_ultimo_servicio=null`
- AND `entrenar_modelos_salud` excluye ese registro (filtro `km_desde_ultimo_servicio > 0`)
