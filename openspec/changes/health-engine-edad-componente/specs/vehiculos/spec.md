# vehiculos Specification (delta — health-engine-edad-componente)

## ADDED Requirements

### Requirement: Cap por antigüedad del componente (no del vehículo)

Para componentes en `_AGE_HARD_CAPS` (líquido de frenos, refrigerante, neumáticos,
correa, amortiguadores), el `HealthEngine` **SHALL** calcular la edad relevante como
tiempo transcurrido desde el **último servicio confirmado** del componente cuando
`historial_conocido=True` y `fecha_ultimo_servicio` está definida.

Cuando no hay historial confirmado, **SHALL** usar la antigüedad de fabricación del
vehículo como estimación conservadora.

#### Scenario: Líquido de frenos recién cambiado en vehículo antiguo

- GIVEN un vehículo de 13 años con `brake-fluid` servido hoy vía checklist `REEMPLAZA`
- AND `historial_conocido=True`, `fecha_ultimo_servicio=now`, `historial_fuente='CHECKLIST'`
- WHEN `HealthEngine.calcular_salud_vehiculo` recalcula
- THEN `salud_porcentaje` **SHALL** ser ≥ 70 % (típicamente ~100 %)
- AND **SHALL NOT** aplicar cap de 20 % por antigüedad del vehículo

#### Scenario: Componente sin historial en vehículo antiguo

- GIVEN un vehículo de 13 años con `brake-fluid` sin `fecha_ultimo_servicio` confirmada
- AND `historial_conocido=False`
- WHEN `HealthEngine` recalcula
- THEN `salud_porcentaje` **SHALL** estar capada a ≤ 20 % por antigüedad conservadora

#### Scenario: Componente cambiado hace más del límite crítico

- GIVEN `brake-fluid` con último servicio hace 6 años (`historial_conocido=True`)
- WHEN `HealthEngine` recalcula
- THEN `salud_porcentaje` **SHALL** ser ≤ 20 % (cap crítico por edad del componente)

### Requirement: Mensajes de alerta coherentes con el factor limitante

El `mensaje_alerta` **SHALL NOT** afirmar "Intervalo por tiempo (~0 meses desde último
servicio)" cuando la salud fue limitada por el cap de antigüedad del vehículo sin
historial, ni cuando el eje temporal no fue el factor dominante.

#### Scenario: Servicio reciente sin degradación temporal

- GIVEN un componente con servicio hace < 1 mes y salud alta
- WHEN se genera `mensaje_alerta`
- THEN no incluye aviso de intervalo por tiempo con ~0 meses

### Requirement: Eventos ML con intervalo válido

Al registrar `EventoSaludVehiculo` tipo `SERVICIO_REALIZADO` desde checklist
`REEMPLAZA`, el sistema **SHALL** setear `km_desde_ultimo_servicio` solo cuando
existía ancla previa confirmada (`historial_conocido=True` y `km_ultimo_servicio>0`
antes del servicio). El primer servicio que establece ancla **SHALL** registrar
`km_desde_ultimo_servicio=null` para excluirlo del entrenamiento scikit-learn.

#### Scenario: Primer cambio de componente sin historial previo

- GIVEN un `ComponenteSaludVehiculo` recién creado por el engine sin historial real
- WHEN se completa checklist `REEMPLAZA` para ese componente
- THEN se crea `EventoSaludVehiculo(SERVICIO_REALIZADO)` con `km_desde_ultimo_servicio=null`
- AND el entrenamiento ML (`entrenar_modelos_salud`) no usa ese evento como muestra de intervalo

## MODIFIED Requirements

### Requirement: Predicciones inteligentes de mantenimiento (MODIFICADO)

Las recomendaciones de antigüedad en `PredictorSalud` **SHALL** usar la edad del
componente (tiempo desde último servicio) cuando hay historial confirmado, alineada
con `_age_health_cap` del HealthEngine.

Los umbrales de `nivel_alerta` en `tasks._nivel_alerta_desde_pct` **SHALL** coincidir
con HealthEngine: 70 / 40 / 10.
