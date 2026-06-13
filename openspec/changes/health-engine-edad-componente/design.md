# Diseño técnico — Health Engine (edad por componente)

## Pipeline de actualización de salud

```
ChecklistInstance COMPLETADO
  └─ post_save (checklists/signals.py)
       ├─ invalidate_vehicle_health_cache
       ├─ actualizar_salud_desde_checklist  [Celery: default]
       │    ├─ Actualizar odómetro del vehículo (km del checklist)
       │    ├─ Por cada ítem con componente_salud_asociado:
       │    │    REEMPLAZA → salud=100, salud_anclada_pct=null, historial CHECKLIST
       │    │    INSPECCIONA → salud=pct declarado, salud_anclada_pct=pct
       │    ├─ EventoSaludVehiculo (dataset ML)
       │    └─ calcular_salud_vehiculo_async.delay(force=True)
       └─ generar_recomendaciones_checklist  [Celery: default, +5s]
            └─ checklist_recommender (ML + colaborativo)

calcular_salud_vehiculo_async
  └─ HealthEngine.calcular_salud_vehiculo(vehicle_id)
       └─ Por cada ComponenteSalud con regla aplicable:
            Weibull km + Weibull tiempo → min()
            → cap conducción → cap edad componente → cap fuente historial
            → nivel_alerta (70/40/10)
```

**Importante:** el checklist escribe el ancla; el HealthEngine **recalcula** y es la
fuente de verdad persistida. Cualquier cap posterior (edad, conducción, fuente)
puede bajar la salud que el checklist acaba de setear.

## Algoritmo Weibull (doble eje)

Por componente, con regla `ReglaMantenimientoEspecifica` (prioridad) o `Generica`:

```
salud_km     = exp(-(km_recorridos / eta)^beta) × 100
salud_tiempo = exp(-(meses_desde_servicio / intervalo_meses)^beta) × 100   [si aplica]
salud_pct    = min(salud_km, salud_tiempo)
```

- `km_recorridos` = `vehiculo.kilometraje - km_ultimo_servicio` (o ancla Weibull si inspección).
- `fecha_ultimo_servicio` ancla el eje temporal cuando hay historial conocido.

Modo **historial desconocido** (`historial_conocido=False`, `km_ultimo_servicio=0`):
estima ciclo con `km_total % eta` (piso `eta × 0.5`).

## Cap por antigüedad (`_AGE_HARD_CAPS`)

Componentes de goma/química: `brake-fluid`, `coolant`, `tires`, `timing-belt`, `shocks`
(+ aliases `liquido-frenos`, etc.).

| Slug | Óptimo (años) | Crítico (años) | Salud máx. si > crítico |
|------|---------------|----------------|-------------------------|
| brake-fluid | 2 | 4 | 20 % |
| coolant | 3 | 5 | 20 % |
| tires | 5 | 10 | 15 % |
| timing-belt | 6 | 10 | 10 % |
| shocks | 8 | 15 | 15 % |

### Regla corregida (2026-06-12)

```
SI historial_conocido AND fecha_ultimo_servicio:
    años_componente = (now - fecha_ultimo_servicio) / 365.25
SINO:
    años_componente = now.year - vehiculo.year   # conservador
```

- Líquido cambiado **hoy** en auto de 13 años → `años_componente ≈ 0` → **sin cap** → ~100 %.
- Auto de 13 años **sin registro de cambio** → cap a 20 % (protección al usuario).

Entre óptimo y crítico: degradación proporcional (salud_max lineal 70 % → salud_min_critico).

## Caps adicionales (orden de aplicación)

1. Weibull km + tiempo
2. `meses_critico` de regla → cap 25 %
3. Factor conducción (`_WEAR_BY_DRIVING_SLUGS`, km/día)
4. **Cap edad componente** (`_age_health_cap`)
5. Cap fuente `USUARIO_DECLARADO` → máx 65 %

## Umbrales nivel_alerta (canónicos)

| Rango salud | Nivel |
|-------------|-------|
| ≥ 70 % | OPTIMO |
| ≥ 40 % | ATENCION |
| ≥ 10 % | URGENTE |
| < 10 % | CRITICO |

Usar los mismos en `HealthEngine` y `tasks._nivel_alerta_desde_pct`.

## scikit-learn (PredictorSalud)

Tres capas (prioridad descendente al mostrar km estimado):

1. **Bootstrap** — km/día (`ViajeRegistrado`), Weibull, clima, conducción.
2. **RandomForestRegressor** — por slug, ≥30 eventos `SERVICIO_REALIZADO` + `NIVEL_CRITICO`.
3. **Similares** — marca/modelo/año±2 desde `EventoSaludVehiculo`.

Entrenamiento: `entrenar_modelos_salud_async` (domingo 06:00 UTC, cola `heavy`).

### Calidad dataset ML

`SERVICIO_REALIZADO` con `km_desde_ultimo_servicio > 0` **solo** si existía ancla
previa confirmada (`historial_conocido` + `km_ultimo_servicio > 0` antes del servicio).
Primer servicio en componente sin historial → evento con `km_desde=null` (auditoría,
excluido del entrenamiento).

## Celery

| Tarea | Cola | Disparo |
|-------|------|---------|
| `actualizar_salud_desde_checklist` | default | post_save checklist COMPLETADO |
| `calcular_salud_vehiculo_async` | default | tras checklist, viaje, batch |
| `entrenar_modelos_salud_async` | heavy | beat semanal |
| `recalcular_salud_vehiculos_*` | heavy | beat 6h / diario |

Worker Render: `-Q default,heavy`.

## Extensibilidad (nuevos componentes/servicios)

1. Crear `ComponenteSalud` + regla en `ReglaMantenimientoGenerica/Especifica`.
2. Vincular ítems de checklist: `componente_salud_asociado` + `tipo_actualizacion`.
3. Si degrada por edad (goma/química): agregar slug a `_AGE_HARD_CAPS` y `_AGE_HARD_CAPS_PREDICTOR`.
4. Ejecutar `populate_checklists_por_servicio` (idempotente en deploy).
5. ML aprende automáticamente al acumular eventos (sin cambio de código).
