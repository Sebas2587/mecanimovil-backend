# health-engine-edad-componente

## Why

Tras completar un servicio con regla `REEMPLAZA` (ej. cambio de líquido de frenos),
el checklist dejaba el componente al 100 % pero el `HealthEngine` lo recalculaba
al 20 % en vehículos antiguos. La causa: `_age_health_cap` usaba la **antigüedad
de fabricación del vehículo** en lugar del **tiempo desde el último cambio del
componente**. El diagnóstico ML mostraba mensajes contradictorios ("~0 meses desde
último servicio" + "vehículo de 13 años supera vida útil").

## What Changes

- `_age_health_cap` y `_component_age_years` miden edad del componente desde
  `fecha_ultimo_servicio` cuando `historial_conocido=True`.
- Sin historial confirmado → fallback conservador a antigüedad del vehículo.
- Mensaje "Intervalo por tiempo" solo cuando el eje temporal Weibull limita la salud.
- Umbrales `nivel_alerta` unificados (70/40/10) entre `tasks.py` y `HealthEngine`.
- `PredictorSalud` alinea recomendaciones de antigüedad con la misma lógica.
- Eventos ML `SERVICIO_REALIZADO`: `km_desde_ultimo_servicio` solo si había ancla previa confirmada.
- Tests de regresión en `test_health_engine_age_cap.py`.
- Spec canónica y skill OpenSpec documentando el pipeline completo.
