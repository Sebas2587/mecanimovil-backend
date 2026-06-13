---
name: openspec-health-engine
description: >-
  Referencia del algoritmo de salud vehicular Mecanimovil: HealthEngine Weibull,
  caps por edad de componente, pipeline Celery post-checklist, PredictorSalud ML
  y extensibilidad. Usar al editar health_engine.py, predictor_salud.py,
  tasks.py (actualizar_salud_desde_checklist), models_health.py, checklists/signals
  o specs en openspec/specs/vehiculos/.
license: MIT
metadata:
  author: mecanimovil
  version: "1.0"
---

# Health Engine — referencia para agentes

Lee también: `openspec/specs/vehiculos/spec.md`, `openspec/changes/health-engine-edad-componente/design.md`.

## Archivos clave

| Archivo | Rol |
|---------|-----|
| `vehiculos/services/health_engine.py` | Cálculo Weibull, caps, persistencia |
| `vehiculos/tasks.py` | Post-checklist, eventos ML, Celery |
| `vehiculos/services/predictor_salud.py` | Bootstrap + scikit-learn + similares |
| `checklists/signals.py` | Dispara tareas al completar checklist |
| `vehiculos/models_health.py` | ComponenteSalud, reglas, EventoSaludVehiculo |

## Flujo post-checklist (orden estricto)

1. Checklist → `COMPLETADO` → `invalidar_cache_salud_vehiculo`
2. `actualizar_salud_desde_checklist(checklist_id, vehicle_id)`:
   - Actualiza odómetro si km del checklist > km actual
   - Por ítem con `componente_salud_asociado`:
     - **REEMPLAZA**: salud=100, `salud_anclada_pct=null`, `historial_fuente=CHECKLIST`
     - **INSPECCIONA**: salud=pct, `salud_anclada_pct=pct`
   - `EventoSaludVehiculo` para ML
   - Encola `calcular_salud_vehiculo_async(force=True)`
3. `HealthEngine.calcular_salud_vehiculo` **recalcula y pisa** salud/nivel/mensaje

Si el usuario ve salud incorrecta tras servicio reciente, revisar caps en paso 3
(especialmente `_age_health_cap`), no asumir fallo de Celery si el km sí se actualizó.

## Fórmula base (Weibull)

```
salud_km     = exp(-(km_recorridos / eta)^beta) × 100
salud_tiempo = exp(-(meses / intervalo_meses)^beta) × 100   # si regla tiene meses
salud        = min(salud_km, salud_tiempo)
```

Luego en orden: cap conducción → **cap edad componente** → cap fuente USUARIO_DECLARADO.

## Cap edad — regla crítica

**Medir edad del COMPONENTE**, no del vehículo:

- Con `historial_conocido=True` + `fecha_ultimo_servicio` → años desde último cambio
- Sin historial → años desde `vehiculo.year` (conservador)

Slugs en `_AGE_HARD_CAPS`: `brake-fluid`, `coolant`, `tires`, `timing-belt`, `shocks` (+ aliases).

Ejemplo bug corregido: líquido frenos cambiado hoy en auto 2013 → ~100 %, no 20 %.

## Nivel alerta (70 / 40 / 10)

| Salud | Nivel |
|-------|-------|
| ≥ 70 | OPTIMO |
| ≥ 40 | ATENCION |
| ≥ 10 | URGENTE |
| < 10 | CRITICO |

Debe coincidir en `HealthEngine` y `tasks._nivel_alerta_desde_pct`.

## ML (PredictorSalud)

- Entrena con eventos `SERVICIO_REALIZADO` + `NIVEL_CRITICO`, `km_desde > 0`, ≥30 muestras
- Primer `REEMPLAZA` sin historial previo → evento con `km_desde=null` (no entrena intervalo)
- Re-entreno: Celery beat domingo 06:00 UTC, cola `heavy`
- Bootstrap siempre disponible; ML opcional por slug

## Agregar nuevo componente/servicio

1. `ComponenteSalud` + `ReglaMantenimientoGenerica` (eta, beta, intervalo_meses)
2. Checklist item: FK `componente_salud_asociado` + `tipo_actualizacion` REEMPLAZA/INSPECCIONA
3. Si degrada por edad química/goma: añadir slug a `_AGE_HARD_CAPS` y predictor
4. `populate_checklists_por_servicio` en deploy
5. ML aprende solo al acumular eventos reales

## Comandos útiles

```bash
# Recalcular un vehículo (shell)
python manage.py shell -c "from mecanimovilapp.apps.vehiculos.tasks import calcular_estado_salud_interno; calcular_estado_salud_interno(<ID>)"

# Reprocesar checklists históricos
python manage.py procesar_checklists_historicos

# Entrenar modelos ML
python manage.py entrenar_modelos_salud
```

## Tests

`vehiculos/tests/test_health_engine_age_cap.py` — caps por edad de componente y umbrales.
