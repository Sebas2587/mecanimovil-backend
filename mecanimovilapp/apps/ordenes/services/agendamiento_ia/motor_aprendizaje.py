"""
Aprendizaje acumulativo de patrones (sin guardar consultas efímeras de analizar-necesidad).

Solo se alimenta desde solicitudes con descripcion confirmada + servicios elegidos.
Almacena fragmentos de palabras clave normalizadas, no oraciones completas con PII.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any

from django.db.models import F

from mecanimovilapp.apps.ordenes.models import PatronAprendizajeNecesidad, SolicitudServicioPublica
from mecanimovilapp.apps.servicios.models import Servicio

from .lexico_necesidad import detectar_sintomas, normalizar_texto

logger = logging.getLogger(__name__)

_STOPWORDS = frozenset({
    'para', 'por', 'con', 'sin', 'del', 'las', 'los', 'una', 'uno', 'que', 'como',
    'pero', 'muy', 'mas', 'más', 'este', 'esta', 'ese', 'esa', 'auto', 'carro', 'vehiculo',
    'vehículo', 'tengo', 'tiene', 'hace', 'desde', 'hace', 'solo', 'solo', 'need',
})

_MIN_FRAGMENTO_TOKENS = 2
_MAX_FRAGMENTOS_POR_REGISTRO = 12


def _tokens_significativos(texto: str, max_tokens: int = 8) -> list[str]:
    norm = normalizar_texto(texto)
    palabras = [p for p in re.split(r'\W+', norm) if len(p) > 2 and p not in _STOPWORDS]
    # preservar orden, sin duplicados
    seen: set[str] = set()
    out: list[str] = []
    for p in palabras:
        if p not in seen:
            seen.add(p)
            out.append(p)
        if len(out) >= max_tokens:
            break
    return out


def _generar_fragmentos(texto: str) -> list[str]:
    """Genera fragmentos de 2-3 palabras para indexar patrones."""
    tokens = _tokens_significativos(texto, max_tokens=10)
    if not tokens:
        return []
    fragmentos: list[str] = []
    # unigramas relevantes (síntomas detectados añaden peso)
    for t in tokens[:6]:
        fragmentos.append(t)
    # bigramas y trigrama
    for i in range(len(tokens) - 1):
        fragmentos.append(f'{tokens[i]} {tokens[i + 1]}')
    if len(tokens) >= 3:
        fragmentos.append(f'{tokens[0]} {tokens[1]} {tokens[2]}')
    # dedupe manteniendo orden
    seen: set[str] = set()
    uniq: list[str] = []
    for f in fragmentos:
        f = f[:120]
        if f not in seen:
            seen.add(f)
            uniq.append(f)
        if len(uniq) >= _MAX_FRAGMENTOS_POR_REGISTRO:
            break
    return uniq


def _slug_desde_componentes(componentes_salud: list[dict] | None) -> str:
    if not componentes_salud:
        return ''
    critico = None
    peor_salud = 101.0
    for comp in componentes_salud:
        nivel = (comp.get('nivel_alerta') or comp.get('status') or '').upper()
        salud = comp.get('salud_porcentaje') or comp.get('salud')
        try:
            salud_f = float(salud) if salud is not None else 100.0
        except (TypeError, ValueError):
            salud_f = 100.0
        if nivel in ('CRITICO', 'CRITICAL', 'URGENTE') or salud_f < peor_salud:
            peor_salud = salud_f
            critico = (comp.get('slug') or '').strip()
    return critico or ''


def registrar_aprendizaje_desde_solicitud(
    solicitud: SolicitudServicioPublica,
    *,
    componentes_salud: list[dict] | None = None,
) -> int:
    """
    Incrementa patrones a partir de una solicitud ya persistida.
    Retorna cantidad de patrones tocados.
    """
    descripcion = (solicitud.descripcion_problema or '').strip()
    if len(descripcion) < 8:
        return 0

    servicio_ids = list(solicitud.servicios_solicitados.values_list('id', flat=True))
    if not servicio_ids:
        return 0

    modelo_id = None
    if solicitud.vehiculo_id and solicitud.vehiculo and solicitud.vehiculo.modelo_id:
        modelo_id = solicitud.vehiculo.modelo_id

    slug = _slug_desde_componentes(componentes_salud)
    if not slug:
        reglas = detectar_sintomas(descripcion)
        if reglas:
            slug = (reglas[0].slugs_salud[0] if reglas[0].slugs_salud else '') or reglas[0].id

    fragmentos = _generar_fragmentos(descripcion)
    if not fragmentos:
        return 0

    actualizados = 0
    for fragmento in fragmentos:
        for sid in servicio_ids:
            try:
                obj, created = PatronAprendizajeNecesidad.objects.get_or_create(
                    fragmento=fragmento,
                    servicio_id=sid,
                    componente_slug=slug or '',
                    modelo_id=modelo_id,
                    defaults={'confirmaciones': 1},
                )
                if not created:
                    PatronAprendizajeNecesidad.objects.filter(pk=obj.pk).update(
                        confirmaciones=F('confirmaciones') + 1,
                    )
                actualizados += 1
            except Exception:
                logger.exception('Error registrando patrón aprendizaje (sin texto usuario)')
    return actualizados


def boost_servicios_desde_aprendizaje(
    texto: str,
    servicios: list[Servicio],
    *,
    modelo_id: int | None = None,
    componentes_salud: list[dict] | None = None,
) -> dict[int, tuple[float, str]]:
    """
    servicio_id -> (boost 0-1, razon)
    """
    fragmentos = _generar_fragmentos(texto)
    if not fragmentos:
        return {}

    servicio_ids = {s.id for s in servicios}
    slug = _slug_desde_componentes(componentes_salud)
    boosts: dict[int, tuple[float, str]] = {}

    for fragmento in fragmentos:
        qs = PatronAprendizajeNecesidad.objects.filter(
            fragmento=fragmento,
            servicio_id__in=servicio_ids,
        )
        if modelo_id:
            from django.db.models import Q

            qs = qs.filter(Q(modelo_id=modelo_id) | Q(modelo__isnull=True))
        if slug:
            qs = qs.filter(componente_slug__in=('', slug))

        for patron in qs.order_by('-confirmaciones')[:20]:
            conf = patron.confirmaciones
            boost = min(0.88, 0.42 + 0.12 * math.log1p(conf))
            prev = boosts.get(patron.servicio_id, (0.0, ''))[0]
            if boost > prev:
                boosts[patron.servicio_id] = (
                    boost,
                    f'Otros clientes con síntomas similares eligieron este servicio ({conf}×)',
                )

    # overlap parcial: primer token en patrones almacenados
    if len(fragmentos) >= 1:
        parciales = PatronAprendizajeNecesidad.objects.filter(
            fragmento__icontains=fragmentos[0],
            servicio_id__in=servicio_ids,
        ).order_by('-confirmaciones')[:15]
        for patron in parciales:
            if patron.fragmento in fragmentos:
                continue
            conf = patron.confirmaciones
            boost = min(0.75, 0.35 + 0.1 * math.log1p(conf))
            prev = boosts.get(patron.servicio_id, (0.0, ''))[0]
            if boost > prev:
                boosts[patron.servicio_id] = (
                    boost,
                    'Patrón frecuente en solicitudes parecidas',
                )

    return boosts


def contar_patrones_activos() -> int:
    return PatronAprendizajeNecesidad.objects.count()


def build_metadata_ia_entrada(
    *,
    analisis: dict[str, Any] | None = None,
    componentes_salud: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Resumen persistido al confirmar solicitud (alimenta aprendizaje vía señal m2m).
    No incluye el texto completo de consultas efímeras, solo metadatos del análisis.
    """
    meta: dict[str, Any] = {}
    if analisis:
        if analisis.get('motor_analisis'):
            meta['motor_analisis'] = analisis['motor_analisis']
        if analisis.get('interpretacion'):
            meta['interpretacion'] = (analisis['interpretacion'] or '')[:600]
        if analisis.get('resumen_salud'):
            meta['resumen_salud'] = (analisis['resumen_salud'] or '')[:600]
        if analisis.get('sintomas_detectados'):
            meta['sintomas_detectados'] = list(analisis['sintomas_detectados'])[:12]
        if analisis.get('coherencia_salud_texto') is not None:
            meta['coherencia_salud_texto'] = analisis['coherencia_salud_texto']
        recs = analisis.get('servicios_recomendados') or []
        meta['servicios_recomendados_ids'] = [
            r.get('servicio_id') for r in recs if isinstance(r, dict) and r.get('servicio_id')
        ][:12]
    if componentes_salud:
        meta['componentes_salud'] = [
            {
                'slug': c.get('slug'),
                'nombre': (c.get('nombre') or '')[:80],
                'nivel_alerta': c.get('nivel_alerta') or c.get('status'),
                'salud_porcentaje': c.get('salud_porcentaje') or c.get('salud'),
            }
            for c in componentes_salud[:12]
            if isinstance(c, dict)
        ]
    return meta
