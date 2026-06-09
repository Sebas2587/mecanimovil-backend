"""
ChecklistRecommender — Recomendaciones ML post-checklist para técnico y cliente.

Genera recomendaciones de servicios y mantenimientos una vez que un ChecklistInstance
queda en estado COMPLETADO. Las recomendaciones se construyen en 3 capas:

  1. Anomalías determinísticas
     Compara el estado post-checklist vs. el último evento ML registrado.
     Si hay una caída acelerada de salud → URGENTE o ATENCION.

  2. PredictorSalud ML
     Para componentes en estado deteriorado, invoca el predictor scikit-learn
     (o bootstrap si no hay modelo entrenado) para estimar km/probabilidad de falla.

  3. Inferencia colaborativa
     Para componentes ATENCION sin cobertura ML, usa estadísticas de vehículos
     similares (misma marca/modelo/año) para generar recomendaciones PROACTIVA.

Los resultados se cachean en Redis con TTL 24h (clave: checklist_recomendaciones_{id}).
"""
import logging
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

CACHE_TTL = 86400  # 24 horas
CACHE_KEY_PREFIX = 'checklist_recomendaciones_'

# Umbrales para anomalías determinísticas
UMBRAL_URGENTE_PCT_CAIDA = 20   # caída >= 20pp en <= 60 días
UMBRAL_URGENTE_DIAS = 60
UMBRAL_ATENCION_PCT_CAIDA = 10  # caída >= 10pp en <= 30 días
UMBRAL_ATENCION_DIAS = 30

# Umbrales ML
UMBRAL_ML_KM_URGENTE = 3000
UMBRAL_ML_KM_ATENCION = 5000
UMBRAL_ML_PROB_FALLA_URGENTE = 0.3

# Umbral inferencia colaborativa
UMBRAL_COLAB_KM_MARGEN = 5000
UMBRAL_COLAB_N_CASOS_MIN = 5


def generar_recomendaciones(checklist_id):
    """
    Punto de entrada principal. Retorna la lista de recomendaciones para el
    checklist, leyendo desde cache si está disponible.

    Args:
        checklist_id (int): ID del ChecklistInstance (debe estar COMPLETADO).

    Returns:
        dict con keys: recomendaciones, componentes_actualizados,
                       salud_general_antes, salud_general_despues, generado_en
    """
    cache_key = f'{CACHE_KEY_PREFIX}{checklist_id}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    resultado = _calcular_recomendaciones(checklist_id)
    if resultado:
        try:
            cache.set(cache_key, resultado, timeout=CACHE_TTL)
        except Exception as cache_err:
            logger.warning('ChecklistRecommender: error cacheando resultado: %s', cache_err)
    return resultado


def _calcular_recomendaciones(checklist_id):
    """Calcula las recomendaciones sin usar cache."""
    try:
        from mecanimovilapp.apps.checklists.models import ChecklistInstance
        from mecanimovilapp.apps.vehiculos.models_health import (
            ComponenteSaludVehiculo, EstadoSaludVehiculo, EventoSaludVehiculo,
        )

        try:
            checklist = ChecklistInstance.objects.select_related(
                'orden__vehiculo__marca',
                'orden__vehiculo__modelo',
                'orden__vehiculo__cliente',
            ).get(id=checklist_id)
        except ChecklistInstance.DoesNotExist:
            logger.error('ChecklistRecommender: checklist %s no encontrado', checklist_id)
            return None

        if checklist.estado != 'COMPLETADO':
            logger.warning(
                'ChecklistRecommender: checklist %s no está COMPLETADO (estado=%s)',
                checklist_id, checklist.estado,
            )
            return None

        vehiculo = getattr(checklist.orden, 'vehiculo', None)
        if vehiculo is None:
            return None

        # Snapshot de salud general antes/después
        estado_general = EstadoSaludVehiculo.objects.filter(vehiculo=vehiculo).first()
        salud_general_despues = (
            round(estado_general.salud_general_porcentaje, 1) if estado_general else None
        )

        # Componentes que este checklist actualizó
        componentes_actualizados = _componentes_actualizados_por_checklist(checklist, vehiculo)
        salud_general_antes = _calcular_salud_antes(vehiculo, componentes_actualizados)

        recomendaciones = []

        # ── Capa 1: Anomalías determinísticas ─────────────────────────────
        for comp_data in componentes_actualizados:
            rec = _evaluar_anomalia(vehiculo, comp_data, checklist_id)
            if rec:
                recomendaciones.append(rec)

        # ── Capa 2: PredictorSalud ML ──────────────────────────────────────
        comp_ids_con_rec = {r['componente_slug'] for r in recomendaciones}
        for comp_data in componentes_actualizados:
            if comp_data['slug'] in comp_ids_con_rec:
                continue
            if comp_data['salud_nueva'] is None:
                continue
            nivel = comp_data.get('nivel_alerta_nueva', 'OPTIMO')
            if nivel not in ('URGENTE', 'CRITICO', 'ATENCION'):
                continue
            rec = _evaluar_ml(vehiculo, comp_data)
            if rec:
                recomendaciones.append(rec)
                comp_ids_con_rec.add(comp_data['slug'])

        # ── Capa 3: Inferencia colaborativa ───────────────────────────────
        for comp_data in componentes_actualizados:
            if comp_data['slug'] in comp_ids_con_rec:
                continue
            if comp_data.get('nivel_alerta_nueva') != 'ATENCION':
                continue
            rec = _evaluar_colaborativo(vehiculo, comp_data)
            if rec:
                recomendaciones.append(rec)

        # Resolver servicios sugeridos para cada recomendación
        _enriquecer_con_servicios(recomendaciones, vehiculo)

        # Ordenar: URGENTE → ATENCION → PROACTIVA
        prioridad_orden = {'URGENTE': 0, 'ATENCION': 1, 'PROACTIVA': 2}
        recomendaciones.sort(key=lambda r: prioridad_orden.get(r.get('prioridad', 'PROACTIVA'), 3))

        return {
            'checklist_id': checklist_id,
            'vehiculo_id': vehiculo.id,
            'generado_en': timezone.now().isoformat(),
            'componentes_actualizados': componentes_actualizados,
            'recomendaciones': recomendaciones,
            'salud_general_antes': salud_general_antes,
            'salud_general_despues': salud_general_despues,
        }

    except Exception as e:
        logger.error(
            'ChecklistRecommender: error calculando recomendaciones para checklist %s: %s',
            checklist_id, e, exc_info=True,
        )
        return None


def _componentes_actualizados_por_checklist(checklist, vehiculo):
    """
    Retorna lista de dicts con el estado de cada componente que este
    checklist actualizó (antes y después del update).
    """
    from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludVehiculo
    from mecanimovilapp.apps.vehiculos.tasks import _candidatos_por_componente, _nivel_alerta_desde_pct

    respuestas = list(checklist.respuestas.select_related(
        'item_template__catalog_item',
        'item_template__componente_salud_asociado',
        'item_template__checklist_template',
    ).all())

    candidatos = _candidatos_por_componente(respuestas)
    if not candidatos:
        return []

    comp_ids = list(candidatos.keys())
    estados = {
        c.componente_id: c
        for c in ComponenteSaludVehiculo.objects.filter(
            vehiculo=vehiculo, componente_id__in=comp_ids
        ).select_related('componente')
    }

    resultado = []
    for comp_id, respuesta in candidatos.items():
        comp = respuesta.item_template.componente_salud_asociado
        estado = estados.get(comp_id)
        if estado is None:
            continue

        tipo_act = respuesta.item_template.tipo_actualizacion_efectivo
        salud_nueva = estado.salud_porcentaje  # ya fue actualizada por actualizar_salud_desde_checklist

        resultado.append({
            'componente_id': comp.id,
            'nombre': comp.nombre,
            'slug': comp.slug,
            'icono': comp.icono,
            'tipo_actualizacion': tipo_act,
            'salud_nueva': round(salud_nueva, 1) if salud_nueva is not None else None,
            'nivel_alerta_nueva': estado.nivel_alerta,
            'km_ultimo_servicio': estado.km_ultimo_servicio,
            'fecha_ultimo_servicio': (
                estado.fecha_ultimo_servicio.isoformat()
                if estado.fecha_ultimo_servicio else None
            ),
        })
    return resultado


def _calcular_salud_antes(vehiculo, componentes_actualizados):
    """Estima la salud general anterior usando los datos pre-checklist de EventoSaludVehiculo."""
    from mecanimovilapp.apps.vehiculos.models_health import EventoSaludVehiculo

    if not componentes_actualizados:
        return None

    comp_ids = [c['componente_id'] for c in componentes_actualizados]
    eventos_previos = EventoSaludVehiculo.objects.filter(
        vehiculo=vehiculo,
        componente_id__in=comp_ids,
    ).order_by('componente_id', '-fecha').distinct('componente_id')

    saludes_previas = [e.salud_porcentaje for e in eventos_previos if e.salud_porcentaje is not None]
    if not saludes_previas:
        return None

    return round(sum(saludes_previas) / len(saludes_previas), 1)


def _evaluar_anomalia(vehiculo, comp_data, checklist_id):
    """Capa 1: detecta caída acelerada de salud comparando con evento previo."""
    from mecanimovilapp.apps.vehiculos.models_health import EventoSaludVehiculo

    salud_nueva = comp_data.get('salud_nueva')
    if salud_nueva is None:
        return None

    evento_previo = EventoSaludVehiculo.objects.filter(
        vehiculo=vehiculo,
        componente__id=comp_data['componente_id'],
        tipo_evento__in=['INSPECCION_DECLARADA', 'SERVICIO_REALIZADO'],
    ).exclude(
        checklist_id=checklist_id,
    ).order_by('-fecha').first()

    if evento_previo is None or evento_previo.salud_porcentaje is None:
        return None

    salud_anterior = float(evento_previo.salud_porcentaje)
    caida = salud_anterior - salud_nueva
    if caida <= 0:
        return None

    dias_desde_evento = (timezone.now() - evento_previo.fecha).days

    prioridad = None
    razon = None

    if caida >= UMBRAL_URGENTE_PCT_CAIDA and dias_desde_evento <= UMBRAL_URGENTE_DIAS:
        prioridad = 'URGENTE'
        razon = (
            f'Desgaste acelerado: {comp_data["nombre"]} bajó de {salud_anterior:.0f}% '
            f'a {salud_nueva:.0f}% en {dias_desde_evento} días '
            f'(caída de {caida:.0f}pp en menos de {UMBRAL_URGENTE_DIAS} días).'
        )
    elif caida >= UMBRAL_ATENCION_PCT_CAIDA and dias_desde_evento <= UMBRAL_ATENCION_DIAS:
        prioridad = 'ATENCION'
        razon = (
            f'{comp_data["nombre"]} muestra deterioro notable: {salud_anterior:.0f}% '
            f'→ {salud_nueva:.0f}% en {dias_desde_evento} días.'
        )

    if prioridad is None:
        return None

    return {
        'prioridad': prioridad,
        'componente_id': comp_data['componente_id'],
        'componente_slug': comp_data['slug'],
        'componente_nombre': comp_data['nombre'],
        'razon': razon,
        'confianza': 0.95,
        'fuente': 'ANOMALIA',
        'servicios_sugeridos': [],
    }


def _evaluar_ml(vehiculo, comp_data):
    """Capa 2: usa PredictorSalud para componentes en estado deteriorado."""
    try:
        from mecanimovilapp.apps.vehiculos.services.predictor_salud import (
            predecir_vehiculo,
            estadisticas_similares,
        )

        slug = comp_data['slug']
        predicciones = predecir_vehiculo(vehiculo)

        pred_comp = next(
            (p for p in predicciones if p.get('slug') == slug),
            None,
        )
        if pred_comp is None:
            return None

        km_restantes = pred_comp.get('km_hasta_critico')
        prob_falla_30d = pred_comp.get('probabilidad_falla_30d', 0)
        confianza = pred_comp.get('confianza', 0.5)

        if km_restantes is not None and km_restantes < UMBRAL_ML_KM_URGENTE:
            prioridad = 'URGENTE'
            razon = (
                f'ML predice que {comp_data["nombre"]} alcanzará nivel crítico '
                f'en ~{km_restantes:,} km.'
            )
        elif (km_restantes is not None and km_restantes < UMBRAL_ML_KM_ATENCION) or \
                prob_falla_30d >= UMBRAL_ML_PROB_FALLA_URGENTE:
            prioridad = 'ATENCION'
            if km_restantes is not None:
                razon = f'ML estima {km_restantes:,} km restantes para {comp_data["nombre"]}.'
            else:
                razon = (
                    f'ML estima {prob_falla_30d * 100:.0f}% de probabilidad de falla '
                    f'en 30 días para {comp_data["nombre"]}.'
                )
        else:
            return None

        basado_en = pred_comp.get('basado_en', '')
        if basado_en:
            razon += f' ({basado_en})'

        return {
            'prioridad': prioridad,
            'componente_id': comp_data['componente_id'],
            'componente_slug': slug,
            'componente_nombre': comp_data['nombre'],
            'razon': razon,
            'confianza': round(confianza, 2),
            'fuente': 'ML',
            'servicios_sugeridos': [],
        }

    except Exception as e:
        logger.warning(
            'ChecklistRecommender: error en capa ML para componente %s: %s',
            comp_data.get('slug'), e,
        )
        return None


def _evaluar_colaborativo(vehiculo, comp_data):
    """Capa 3: inferencia por vehículos similares cuando no hay modelo ML."""
    try:
        from mecanimovilapp.apps.vehiculos.services.predictor_salud import estadisticas_similares

        slug = comp_data['slug']
        stats = estadisticas_similares(vehiculo, slug)
        if stats is None or stats.get('n_casos', 0) < UMBRAL_COLAB_N_CASOS_MIN:
            return None

        km_actual = int(getattr(vehiculo, 'kilometraje', 0) or 0)
        km_mediana = stats.get('km_promedio_servicio', 0)
        km_margen = km_mediana - km_actual

        if km_margen > UMBRAL_COLAB_KM_MARGEN:
            return None

        razon = (
            f'{stats["n_casos"]} vehículos similares ({stats["marca"]} {stats["modelo"]}, '
            f'años {stats["rango_year"]}) realizaron mantenimiento de {comp_data["nombre"]} '
            f'entre {stats["km_min"]:,} y {stats["km_max"]:,} km. '
            f'Tu vehículo tiene {km_actual:,} km.'
        )

        return {
            'prioridad': 'PROACTIVA',
            'componente_id': comp_data['componente_id'],
            'componente_slug': slug,
            'componente_nombre': comp_data['nombre'],
            'razon': razon,
            'confianza': round(min(0.9, stats['n_casos'] / 50.0), 2),
            'fuente': 'COLABORATIVO',
            'servicios_sugeridos': [],
        }

    except Exception as e:
        logger.warning(
            'ChecklistRecommender: error en capa colaborativa para componente %s: %s',
            comp_data.get('slug'), e,
        )
        return None


def _enriquecer_con_servicios(recomendaciones, vehiculo):
    """Resuelve los servicios sugeridos para cada recomendación."""
    try:
        from mecanimovilapp.apps.vehiculos.models_health import ComponenteSalud
        from mecanimovilapp.apps.vehiculos.services.componente_servicio_sugerido import (
            ordenar_servicios_asociados,
        )

        tipo_motor = getattr(vehiculo, 'tipo_motor', None) or ''
        comp_ids = [r['componente_id'] for r in recomendaciones if r.get('componente_id')]

        componentes = {
            c.id: c
            for c in ComponenteSalud.objects.prefetch_related(
                'servicios_asociados'
            ).filter(id__in=comp_ids)
        }

        for rec in recomendaciones:
            comp = componentes.get(rec.get('componente_id'))
            if comp is None:
                continue
            servicios_qs = comp.servicios_asociados.all()
            rec['servicios_sugeridos'] = ordenar_servicios_asociados(
                comp.slug, servicios_qs, tipo_motor=tipo_motor
            )[:3]

    except Exception as e:
        logger.warning('ChecklistRecommender: error resolviendo servicios sugeridos: %s', e)
