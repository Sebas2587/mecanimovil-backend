"""Preferencia de repuestos: única lectura + único texto de prompt (D16/D18)."""
from __future__ import annotations

import logging
import re
from typing import Any

from django.conf import settings

from mecanimovilapp.apps.agente_ia.models import (
    AgenteAprendizajeDiario,
    AgenteClienteMemoria,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.calidad_repuesto import (
    CALIDADES,
    detectar_calidad,
)

logger = logging.getLogger(__name__)

ALCANCE_CON = 'con_repuestos'
ALCANCE_SOLO_MO = 'solo_mano_obra'
ALCANCE_INDEF = 'no_definido'

_SOLO_MANO_RE = re.compile(
    r'(?:solo\s+mano\s+de\s+obra|yo\s+pongo\s+(?:los\s+)?repuestos|'
    r'ya\s+tengo\s+(?:la\s+pieza|el\s+repuesto|los\s+repuestos)|sin\s+repuestos)',
    re.I,
)
_PIEZA_EXPLICITA_RE = re.compile(
    r'\b(?:pastillas?|discos?|filtros?|aceite|bater[ií]a|amortiguadores?|'
    r'embrague|buj[ií]as?|correa|kit\s+de\s+distribuci[oó]n)\b',
    re.I,
)
_DIAGNOSTICO_RE = re.compile(r'\b(?:diagn[oó]stico|revisi[oó]n|revisar|chequear)\b', re.I)


def alcance_repuestos_habilitado(config=None) -> bool:
    if not getattr(settings, 'AGENTE_IA_ALCANCE_REPUESTOS_ENABLED', False):
        return False
    if config is not None and not getattr(config, 'habilitado', True):
        return False
    return True


def contexto_repuestos_cliente(taller, external_contact=None, patente: str = '') -> dict[str, Any]:
    """Preferencia para inyectar en cualquier agente.

    Orden: memoria cliente (≥2 muestras) → patente → agregado del taller.
    """
    vacio = {
        'calidad_preferida': '',
        'nivel': 'ninguna',
        'muestras': 0,
        'por_familia': {},
        'patron_taller': '',
        'ultimas_selecciones': [],
    }
    if taller is None:
        return vacio
    taller_id = getattr(taller, 'id', taller)

    if external_contact is not None:
        mem = AgenteClienteMemoria.objects.filter(
            taller_id=taller_id,
            external_contact_id=getattr(external_contact, 'id', external_contact),
        ).first()
        if mem is not None:
            prefs = dict(mem.preferencias_repuestos or {})
            muestras = int(prefs.get('muestras') or 0)
            calidad = (mem.calidad_preferida or prefs.get('calidad_preferida') or '').strip()
            if calidad in CALIDADES and muestras >= 2:
                return {
                    **vacio,
                    'calidad_preferida': calidad,
                    'nivel': 'memoria',
                    'muestras': muestras,
                    'por_familia': dict(prefs.get('por_familia') or {}),
                    'ultimas_selecciones': list(prefs.get('ultimas') or [])[:5],
                }

    patente_ok = (patente or '').strip().upper().replace('-', '').replace(' ', '')
    if patente_ok:
        from mecanimovilapp.apps.ordenes.models import VehiculoPreferenciaRepuesto

        row = VehiculoPreferenciaRepuesto.objects.filter(
            taller_id=taller_id,
            patente=patente_ok[:12],
        ).first()
        if row and row.calidad_preferida in CALIDADES and int(row.muestras or 0) >= 1:
            return {
                **vacio,
                'calidad_preferida': row.calidad_preferida,
                'nivel': 'patente',
                'muestras': int(row.muestras or 0),
                'por_familia': dict(row.por_familia or {}),
            }

    hallazgo = (
        AgenteAprendizajeDiario.objects.filter(
            taller_id=taller_id,
            tipo_hallazgo=AgenteAprendizajeDiario.TIPO_SELECCION_REPUESTO,
        )
        .order_by('-fecha', '-id')
        .first()
    )
    if hallazgo is not None:
        det = dict(hallazgo.detalle_json or {})
        calidad = str(det.get('calidad_preferida') or '').strip()
        muestras = int(det.get('muestras') or 0)
        if calidad in CALIDADES and muestras >= 6:
            return {
                **vacio,
                'calidad_preferida': calidad,
                'nivel': 'taller',
                'muestras': muestras,
                'por_familia': dict(det.get('por_familia') or {}),
                'patron_taller': str(det.get('patron') or ''),
            }
    return vacio


def bloque_prompt_repuestos(ctx: dict[str, Any] | None) -> str:
    """Única función de texto. La inyectan orquestador, seguimiento y agendamiento."""
    ctx = ctx or {}
    calidad = str(ctx.get('calidad_preferida') or '').strip()
    nivel = str(ctx.get('nivel') or 'ninguna')
    if not calidad:
        return (
            'PREFERENCIA DE REPUESTOS: desconocida. No inventes marca ni calidad. '
            'Si el sistema envía botones de calidad, marca calidad_preferida="" y sigue.'
        )
    label = {
        'original': 'original (marca del auto / concesionario)',
        'oem': 'equivalente OEM',
        'alternativo': 'alternativo / más económico',
    }.get(calidad, calidad)
    return (
        f'PREFERENCIA DE REPUESTOS (fuente={nivel}, muestras={int(ctx.get("muestras") or 0)}): '
        f'este cliente suele elegir {label}. ÚSALA y NO preguntes de nuevo. '
        f'NUNCA inventes precios de esa calidad.'
    )


def inferir_alcance_repuestos(texto: str, decision: dict | None = None) -> str:
    decision = decision or {}
    raw = str(decision.get('alcance_repuestos') or '').strip().lower()
    if raw in (ALCANCE_CON, ALCANCE_SOLO_MO, ALCANCE_INDEF):
        if raw == ALCANCE_INDEF and _PIEZA_EXPLICITA_RE.search(texto or ''):
            return ALCANCE_CON
        return raw
    if _SOLO_MANO_RE.search(texto or ''):
        return ALCANCE_SOLO_MO
    if _PIEZA_EXPLICITA_RE.search(texto or ''):
        return ALCANCE_CON
    if _DIAGNOSTICO_RE.search(texto or ''):
        return ALCANCE_INDEF
    return ALCANCE_INDEF


def aplicar_alcance_repuestos(
    datos: dict[str, Any],
    decision: dict[str, Any],
    texto_cliente: str,
) -> dict[str, Any]:
    """Deriva alcance + calidad + piezas y mantiene el flag legado."""
    next_datos = dict(datos or {})
    alcance = inferir_alcance_repuestos(texto_cliente, decision)
    next_datos['alcance_repuestos'] = alcance
    if alcance == ALCANCE_CON:
        next_datos['repuestos_incluidos_ultimo_servicio'] = True
    elif alcance == ALCANCE_SOLO_MO:
        next_datos['repuestos_incluidos_ultimo_servicio'] = False
    elif decision.get('repuestos_incluidos_ultimo_servicio') is not None:
        next_datos['repuestos_incluidos_ultimo_servicio'] = bool(
            decision.get('repuestos_incluidos_ultimo_servicio')
        )

    calidad = str(decision.get('calidad_preferida') or '').strip().lower()
    if calidad not in CALIDADES:
        calidad = detectar_calidad(texto_cliente) or ''
    if calidad in CALIDADES:
        next_datos['calidad_preferida'] = calidad

    piezas = decision.get('piezas_mencionadas')
    if isinstance(piezas, list):
        next_datos['piezas_mencionadas'] = [
            str(p).strip()[:80] for p in piezas if str(p or '').strip()
        ][:8]
    logger.info(
        'agente_ia[alcance] alcance=%s calidad=%s piezas_n=%s',
        alcance,
        next_datos.get('calidad_preferida') or '',
        len(next_datos.get('piezas_mencionadas') or []),
    )
    return next_datos
