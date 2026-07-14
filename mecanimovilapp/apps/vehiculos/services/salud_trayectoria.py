"""
Proyección de salud general a futuro (usada por el motor de valoración).

Problema que resuelve: `proyeccion_engine.project_values` aplicaba la salud
de HOY como un factor único y estático sobre toda la curva de depreciación
(hoy, +1 año, +3 años), sin importar que el vehículo siga (o no) su ritmo real
de mantenciones. Dos autos con la misma salud actual pero historiales de
servicio muy distintos (uno recién revisado, otro con componentes vencidos)
terminaban con la MISMA proyección — de ahí que la curva se viera siempre
igual ("patrón" fijo) en vez de reflejar el comportamiento real del usuario.

Este módulo simula hacia adelante, componente por componente, la misma curva
Weibull que ya usa `HealthEngine` hoy:

    salud_km(t) = exp(-(km_recorridos_futuro / eta) ** beta) * 100

- `km_recorridos_futuro` se proyecta con el ritmo real de uso del vehículo
  (km/día calculado desde `ViajeRegistrado`, igual que `predictor_salud`).
- `eta` (vida útil del componente) es la que el `HealthEngine` ya resolvió y
  persistió en `ComponenteSaludVehiculo.vida_util_proyectada` — no se
  re-resuelven reglas específicas/genéricas aquí para no duplicar esa lógica.
- `beta` usa el valor por defecto de las reglas (2.0), igual que
  `predictor_salud.cdf_falla`, porque el beta específico de la regla no se
  persiste por componente.

Cuando existe un modelo scikit-learn (RandomForest) ya entrenado con datos
reales de la flota para un componente (`predictor_salud.predecir_componente_ml`,
requiere >= 30 eventos reales, ver `ML_TRAINING_THRESHOLD`), se usa el
kilometraje restante que ESE modelo predice — aprendido de servicios
reales de vehículos similares — para afinar cuánto de la vida útil del
componente se consumirá antes del horizonte proyectado, en vez del eta
genérico de la regla. Es la única pieza de este cálculo que es
estrictamente "aprendida" (no fórmula fija); el resto es matemática pura
(Weibull) aplicada con los datos reales de servicio de cada componente.

Si algo falla o no hay componentes con historial suficiente, se retorna
None y el llamador (proyeccion_engine) cae de vuelta a la salud actual
estática — nunca rompe el cálculo de valor.
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

DEFAULT_BETA = 2.0
DIAS_POR_MES = 30.44


def proyectar_salud_general(vehiculo, meses_futuro: float) -> tuple[float, str] | tuple[None, None]:
    """
    Retorna (salud_pct_proyectada, fuente) a `meses_futuro` meses desde hoy.

    fuente in {'weibull_ml', 'weibull_reglas'}. (None, None) si no hay datos
    suficientes para proyectar (vehículo sin componentes de salud aún).
    """
    if meses_futuro is None or meses_futuro <= 0:
        return None, None

    try:
        from .predictor_salud import predecir_componente_ml, _get_avg_km_per_day
    except Exception:
        logger.exception('salud_trayectoria: no se pudo importar predictor_salud')
        return None, None

    componentes = list(
        vehiculo.componentes_salud.select_related('componente').all()
    )
    if not componentes:
        return None, None

    try:
        km_por_dia = float(_get_avg_km_per_day(vehiculo) or 0)
    except Exception:
        km_por_dia = 30.0

    km_hoy = float(vehiculo.kilometraje or 0)
    dias_futuro = meses_futuro * DIAS_POR_MES
    km_futuro = km_hoy + km_por_dia * dias_futuro

    saludes: list[float] = []
    uso_ml = False

    for cs in componentes:
        if not cs.componente:
            continue

        km_ultimo = float(cs.km_ultimo_servicio or 0)
        eta = float(cs.vida_util_proyectada or 0) or 40000.0
        km_recorridos_futuro = max(0.0, km_futuro - km_ultimo)

        try:
            ml = predecir_componente_ml(vehiculo, cs)
        except Exception:
            ml = None

        if ml and ml.get('km_estimados_hasta_servicio'):
            # El modelo entrenado con datos reales dice cuánto km real le
            # queda a ESTE componente en ESTE vehículo desde hoy; usamos esa
            # vida útil restante (medida desde hoy) en vez del eta genérico
            # de la regla para decidir qué tan consumido estará al horizonte.
            km_restante_ml = float(ml['km_estimados_hasta_servicio'])
            km_recorridos_desde_hoy = max(0.0, km_futuro - km_hoy)
            if km_restante_ml > 0:
                fraccion_restante_consumida = min(1.0, km_recorridos_desde_hoy / km_restante_ml)
                salud_hoy_comp = float(cs.salud_porcentaje or 100.0)
                salud_comp = salud_hoy_comp * (1.0 - fraccion_restante_consumida)
                saludes.append(max(0.0, min(100.0, salud_comp)))
                uso_ml = True
                continue

        salud_comp = math.exp(-((km_recorridos_futuro / eta) ** DEFAULT_BETA)) * 100.0
        saludes.append(max(0.0, min(100.0, salud_comp)))

    if not saludes:
        return None, None

    promedio = sum(saludes) / len(saludes)
    fuente = 'weibull_ml' if uso_ml else 'weibull_reglas'
    return round(promedio, 1), fuente
