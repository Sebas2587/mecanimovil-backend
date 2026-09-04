"""Pregunta de calidad con 3 botones WhatsApp (aditiva)."""
from __future__ import annotations

import logging
import re
from typing import Any

from django.conf import settings
from django.utils import timezone

from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.calidad_repuesto import (
    CALIDADES,
    detectar_calidad,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.familias_sensibles import (
    familia_tiene_eje_calidad,
)

logger = logging.getLogger(__name__)

BOTONES_CALIDAD = [
    {'id': 'calidad_original', 'title': 'Original'},
    {'id': 'calidad_oem', 'title': 'Equivalente OEM'},
    {'id': 'calidad_alternativo', 'title': 'Alternativo'},
]


def _vehiculo_presente(datos: dict[str, Any]) -> bool:
    veh = datos.get('vehiculo') or {}
    return bool(
        (veh.get('marca') or '').strip()
        or (veh.get('modelo') or '').strip()
        or (veh.get('patente') or '').strip()
        or (datos.get('patente_enriquecida') or '').strip()
    )


def _piezas(datos: dict[str, Any]) -> list[str]:
    piezas = list(datos.get('piezas_mencionadas') or [])
    if piezas:
        return [str(p) for p in piezas if str(p or '').strip()]
    servs = list(datos.get('servicios') or [])
    if datos.get('servicio_nombre'):
        servs.append(datos.get('servicio_nombre'))
    return [str(s) for s in servs if str(s or '').strip()]


def pregunta_calidad_necesaria(
    *,
    datos: dict[str, Any],
    config,
    ctx_repuestos: dict[str, Any] | None = None,
    opciones: list[dict[str, Any]] | None = None,
    spread_pct: float | None = None,
) -> bool:
    """Una sola vez, nunca sin vehículo, nunca si ya hay preferencia."""
    if not getattr(settings, 'AGENTE_IA_ALCANCE_REPUESTOS_ENABLED', False):
        return False
    if not getattr(settings, 'AGENTE_IA_BOTONES_CALIDAD_ENABLED', False):
        return False
    if config is not None and not getattr(config, 'preguntar_calidad_repuestos', True):
        return False
    if datos.get('pregunta_calidad_enviada') or datos.get('calidad_preferida'):
        return False
    if not _vehiculo_presente(datos):
        return False
    ctx = ctx_repuestos or {}
    if ctx.get('calidad_preferida') and int(ctx.get('muestras') or 0) >= 2:
        return False
    if str(datos.get('alcance_repuestos') or '') == 'solo_mano_obra':
        return False

    piezas = _piezas(datos)
    if not piezas:
        return False
    sensible = any(familia_tiene_eje_calidad(p) for p in piezas)
    ops = [o for o in (opciones or []) if isinstance(o, dict)]
    spread_ok = (spread_pct or 0) >= 25 and len(ops) >= 2
    return bool(sensible or spread_ok)


def parsear_respuesta_calidad(texto_o_button_id: str) -> str | None:
    raw = str(texto_o_button_id or '').strip().lower()
    if not raw:
        return None
    if raw.startswith('calidad_'):
        cand = raw.split('calidad_', 1)[-1]
        return cand if cand in CALIDADES else None
    if raw in ('1', 'original'):
        return 'original'
    if raw in ('2', 'oem', 'equivalente', 'equivalente oem'):
        return 'oem'
    if raw in ('3', 'alternativo', 'alterna'):
        return 'alternativo'
    return detectar_calidad(raw)


def _texto_pregunta(datos: dict[str, Any]) -> str:
    veh = datos.get('vehiculo') or {}
    modelo = ' '.join(
        x for x in [(veh.get('marca') or '').strip(), (veh.get('modelo') or '').strip()] if x
    ) or 'tu auto'
    piezas = _piezas(datos)
    pieza = (piezas[0] if piezas else 'repuesto').strip()
    pieza = re.sub(r'^(cambio de|reemplazo de)\s+', '', pieza, flags=re.I)
    return (
        f'Para el {modelo} tengo tres opciones de {pieza.lower()}. '
        f'¿Cuál te acomoda?'
    )


def _texto_numerado(datos: dict[str, Any]) -> str:
    base = _texto_pregunta(datos)
    return (
        f'{base}\n'
        f'1) Original\n'
        f'2) Equivalente OEM\n'
        f'3) Alternativo\n'
        f'Responde 1, 2 o 3.'
    )


def enviar_pregunta_calidad(
    *,
    conversation,
    proveedor_user_id: int,
    datos: dict[str, Any],
    sesion,
) -> dict[str, Any]:
    from mecanimovilapp.apps.agente_ia.models import AgenteConversacionSesion
    from mecanimovilapp.apps.agente_ia.services.orquestador import enviar_respuesta_agente

    canal = (getattr(conversation, 'source_channel', '') or '').upper()
    usar_botones = (
        canal == 'WHATSAPP'
        and getattr(settings, 'AGENTE_IA_BOTONES_CALIDAD_ENABLED', False)
    )
    texto = _texto_pregunta(datos) if usar_botones else _texto_numerado(datos)
    extra = {'from_agente_ia': True, 'tipo': 'pregunta_calidad'}
    if usar_botones:
        extra['interactive'] = True
        extra['botones'] = BOTONES_CALIDAD
    msg = enviar_respuesta_agente(
        conversation=conversation,
        proveedor_user_id=proveedor_user_id,
        texto=texto,
        extra_metadata=extra,
    )
    next_datos = dict(datos or {})
    next_datos['pregunta_calidad_enviada'] = True
    next_datos['pregunta_calidad_en'] = timezone.now().isoformat()
    sesion.datos_capturados = next_datos
    sesion.estado = AgenteConversacionSesion.ESTADO_ELIGIENDO_REPUESTOS
    sesion.save(update_fields=['datos_capturados', 'estado', 'actualizado_en'])
    logger.info(
        'agente_ia[pregunta_calidad] conv=%s canal=%s enviada=%s',
        getattr(conversation, 'id', None),
        canal,
        bool(msg),
    )
    return {'ok': True, 'enviada': bool(msg), 'mensaje_id': getattr(msg, 'id', None)}
