# Diseño técnico

## Contexto
La app necesita pasar de "métrica de salud calculada" a "información predictiva
útil". El usuario debe ver cuándo cambiará cada componente, con qué probabilidad
y por qué (km, clima, datos de vehículos similares).

## Goals
- Que cada componente muestre un valor distinto incluso sin historial real.
- Que el sistema aprenda de cada checklist completado.
- Que la inferencia funcione desde el día 1 (sin esperar dataset grande).
- Que el costo de inferencia sea despreciable (cache 30 min).

## Non-goals
- Diagnóstico médico de fallos puntuales (ej. "esta pieza específica fallará").
- Reemplazar a la regla Weibull existente — la complementa.
- Entrenar en producción HTTP — el entrenamiento es offline (Celery beat).

## Decisión: 3 capas en lugar de "ML puro"

Razón: los datos reales del sistema todavía son escasos. Si solo se usara ML
puro, la inferencia sería pobre o nula durante meses. La capa **bootstrap**
garantiza utilidad desde el día 1; la **ML** mejora cuando hay datos; la
**similares** ofrece referencias colaborativas inmediatas a partir del primer
servicio registrado.

```
predict(vehiculo, componente):
  # 1. base aritmética con datos del usuario
  base = bootstrap(km/día, clima, eta_weibull)
  # 2. opcional: refinar con scikit-learn si hay modelo entrenado
  if ml_model_existe(componente):
      base.km = ml_model.predict(features)
  # 3. anexar referencia colaborativa
  base.similares = aggregate(EventoSaludVehiculo, marca, modelo, year ± 2)
  return base
```

## Algoritmo ML elegido

`RandomForestRegressor` (n_estimators=80, max_depth=12, min_samples_leaf=2):
- Maneja categorías codificadas (marca/modelo/motor) sin asumir linealidad.
- Robusto frente a pocos datos y outliers.
- Importancia de features interpretable para depurar.
- Permite entrenamiento incremental por componente sin retocar Weibull.

Alternativas consideradas:
- `LinearRegression`: too simple para relaciones no lineales (km vs vida útil).
- `GradientBoosting`: mejor accuracy potencial pero requiere más datos y tuning.
- Decision Tree solo: alto overfitting con datasets pequeños.

## Almacenamiento de modelos

`MEDIA_ROOT/ml_models/{slug}.joblib` con bundle `{regressor, encoders, features, n_samples, mae_km}`.
Cache en memoria por proceso (`_loaded_models`) limpiado al re-entrenar.

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Dataset insuficiente → modelo malo | Threshold de 30 muestras + capa bootstrap como fallback |
| Sklearn no disponible en runtime | `try/except ImportError` retorna `None`; bootstrap funciona igual |
| Re-entrenamiento bloquea worker | Cola `heavy`, soft_time_limit 1500s, schedule 06:00 UTC domingos |
| Feature drift entre re-entrenamientos | Encoders persistidos en el bundle joblib |
| Eventos duplicados saturan tabla | dedup por (vehículo, componente, día) en NIVEL_CRITICO |

## Métricas a monitorear

- `EventoSaludVehiculo.objects.count()` por tipo y por componente (crecimiento).
- MAE por componente (logueado en management command).
- Cache hit rate del endpoint de predicciones (Redis).
- Latencia P95 del endpoint (debe ser < 200 ms con cache, < 1.5 s en cold).
