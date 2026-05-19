"""
Interpretación de métricas de salud y cruce con la necesidad escrita por el usuario.
"""
from __future__ import annotations

from typing import Any

from .lexico_necesidad import REGLAS_SINTOMA, detectar_sintomas, normalizar_texto

_SLUG_A_REGLA: dict[str, str] = {
    'brakes': 'frenos',
    'brake-discs': 'frenos',
    'brake-fluid': 'frenos',
    'oil': 'motor_aceite',
    'oil-filter': 'motor_aceite',
    'spark-plug': 'motor_aceite',
    'coolant': 'refrigeracion',
    'battery': 'arranque_bateria',
    'shocks': 'suspension_neumaticos',
    'tires': 'suspension_neumaticos',
    'air-filter': 'frenos_aire',
    'cabin-filter': 'climatizacion',
}

_NIVEL_CRITICO = frozenset({'CRITICO', 'CRITICAL', 'URGENTE', 'ATENCION', 'WARNING'})


def _salud_float(comp: dict) -> float:
    salud = comp.get('salud_porcentaje') or comp.get('salud')
    try:
        return float(salud) if salud is not None else 100.0
    except (TypeError, ValueError):
        return 100.0


def _nivel(comp: dict) -> str:
    return (comp.get('nivel_alerta') or comp.get('status') or '').upper()


def cargar_componentes_salud_desde_bd(vehiculo_id: int) -> list[dict]:
    """Si el cliente no envió salud, la leemos del vehículo."""
    try:
        from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludVehiculo

        rows = (
            ComponenteSaludVehiculo.objects.filter(vehiculo_id=vehiculo_id)
            .select_related('componente')
            .order_by('salud_porcentaje')[:15]
        )
        out: list[dict] = []
        for row in rows:
            comp = row.componente
            out.append({
                'slug': comp.slug if comp else '',
                'nombre': comp.nombre if comp else 'Componente',
                'nivel_alerta': row.nivel_alerta or '',
                'salud_porcentaje': row.salud_porcentaje,
                'servicios_asociados': [],
            })
        return out
    except Exception:
        return []


def fusionar_componentes_salud(
    enviados: list[dict] | None,
    vehiculo_id: int | None,
) -> list[dict]:
    base = list(enviados or [])
    if base or not vehiculo_id:
        return base
    return cargar_componentes_salud_desde_bd(vehiculo_id)


def interpretar_metricas_salud(componentes_salud: list[dict] | None) -> dict[str, Any]:
    """
    Resumen legible de métricas para el cliente y el motor de ranking.
    """
    if not componentes_salud:
        return {
            'resumen_salud': None,
            'componentes_criticos': [],
            'slugs_prioritarios': [],
        }

    criticos: list[dict] = []
    lineas: list[str] = []
    slugs: list[str] = []

    for comp in componentes_salud:
        nombre = comp.get('nombre') or comp.get('slug') or 'Componente'
        slug = (comp.get('slug') or '').strip()
        nivel = _nivel(comp)
        salud = _salud_float(comp)
        es_critico = nivel in _NIVEL_CRITICO or salud < 45

        if es_critico:
            criticos.append({
                'slug': slug,
                'nombre': nombre,
                'nivel_alerta': nivel or 'ATENCION',
                'salud_porcentaje': salud,
            })
            slugs.append(slug)
            if salud < 30:
                lineas.append(f'{nombre} en estado crítico ({salud:.0f}% de vida útil).')
            elif salud < 50:
                lineas.append(f'{nombre} requiere atención pronto ({salud:.0f}% de vida útil).')
            else:
                lineas.append(f'{nombre}: alerta {nivel.lower() or "activa"}.')

    if not lineas:
        peor = min(componentes_salud, key=_salud_float)
        nombre = peor.get('nombre') or 'Componente'
        salud = _salud_float(peor)
        if salud < 70:
            lineas.append(f'El componente con mayor desgaste es {nombre} ({salud:.0f}%).')

    resumen = None
    if lineas:
        resumen = 'Según el historial de salud de tu vehículo: ' + ' '.join(lineas[:3])

    return {
        'resumen_salud': resumen,
        'componentes_criticos': criticos[:6],
        'slugs_prioritarios': slugs[:6],
    }


def cruzar_salud_con_texto(
    texto: str,
    componentes_salud: list[dict] | None,
    interpretacion_salud: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Contrasta lo que dice el usuario con métricas de salud.
  """
    interpretacion_salud = interpretacion_salud or interpretar_metricas_salud(componentes_salud)
    reglas_texto = {r.id for r in detectar_sintomas(texto)}
    alertas: list[str] = []
    refuerzos: dict[str, str] = {}

    reglas_por_id = {r.id: r for r in REGLAS_SINTOMA}

    for crit in interpretacion_salud.get('componentes_criticos') or []:
        slug = crit.get('slug') or ''
        regla_id = _SLUG_A_REGLA.get(slug.replace('_', '-'), '')
        if not regla_id:
            continue
        regla = reglas_por_id.get(regla_id)
        if not regla:
            continue
        nombre = crit.get('nombre') or slug
        if regla_id not in reglas_texto and (texto or '').strip():
            alertas.append(
                f'Tu {nombre.lower()} está con desgaste elevado; conviene revisarlo aunque no lo hayas mencionado.'
            )
            refuerzos[regla_id] = regla.interpretacion
        elif regla_id in reglas_texto:
            refuerzos[regla_id] = (
                f'Coincide con la salud de {nombre.lower()}: lo que describes encaja con el desgaste registrado.'
            )

    coherencia = 1.0
    if reglas_texto and interpretacion_salud.get('componentes_criticos'):
        slugs_crit = {c.get('slug') for c in interpretacion_salud['componentes_criticos']}
        reglas_salud = {_SLUG_A_REGLA.get((s or '').replace('_', '-'), '') for s in slugs_crit}
        reglas_salud.discard('')
        if reglas_salud and not reglas_texto.intersection(reglas_salud):
            coherencia = 0.45
            if not alertas:
                alertas.append(
                    'Lo que describes podría ser distinto al componente con mayor desgaste según el historial del auto. '
                    'Te sugerimos revisar ambos.'
                )

    interpretacion_cruzada = None
    if refuerzos:
        interpretacion_cruzada = ' '.join(list(refuerzos.values())[:2])
    elif interpretacion_salud.get('resumen_salud') and not (texto or '').strip():
        interpretacion_cruzada = interpretacion_salud['resumen_salud']

    return {
        'alertas_cruce': alertas[:3],
        'interpretacion_cruzada': interpretacion_cruzada,
        'coherencia_salud_texto': round(coherencia, 2),
        'refuerzo_reglas': list(refuerzos.keys()),
    }
