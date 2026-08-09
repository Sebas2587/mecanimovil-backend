"""Aprendizaje de cotizaciones enviadas por marca/modelo/servicio.

Al enviar al cliente, se guarda una plantilla automática reutilizable y se
indexan los repuestos en PrecioRepuestoWeb (dominio historial-taller) para que
IA y agente reusen precios/marcas en servicios similares del mismo vehículo.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .enriquecer_repuestos import _clave_fuzzy, _marca_repuesto_valida, _norm, _to_int_clp

logger = logging.getLogger(__name__)

_DOMINIO_HISTORIAL = 'historial-taller'
_TTL_HISTORIAL_DIAS = 90


def _servicio_tokens(nombre: str) -> set[str]:
    return {t for t in _norm(nombre).split() if len(t) > 2}


def _servicios_similares(a: str, b: str) -> bool:
    ta, tb = _servicio_tokens(a), _servicio_tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    inter = ta & tb
    return len(inter) >= max(1, min(len(ta), len(tb)) // 2)


def _modelo_coincide(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _titulo_plantilla_auto(*, marca: str, modelo: str, servicio: str) -> str:
    veh = ' '.join(p for p in (marca.strip(), modelo.strip()) if p).strip() or 'Vehículo'
    serv = (servicio or 'Servicio').strip()[:80]
    return f'Auto: {veh} — {serv}'[:255]


def _seed_precios_desde_cotizacion(cotizacion) -> int:
    """Indexa repuestos enviados en PrecioRepuestoWeb para reuso sin Gemini."""
    from mecanimovilapp.apps.ordenes.models import PrecioRepuestoWeb
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
        clave_cache_repuesto,
    )

    reps = cotizacion.repuestos or []
    if not isinstance(reps, list):
        return 0
    ttl = max(
        _TTL_HISTORIAL_DIAS,
        int(getattr(settings, 'BUSQUEDA_WEB_REPUESTOS_TTL_DIAS', 14) or 14) * 4,
    )
    expira = timezone.now() + timedelta(days=ttl)
    upserts = 0
    for raw in reps:
        if not isinstance(raw, dict):
            continue
        nombre = str(raw.get('nombre') or '').strip()
        if not nombre:
            continue
        precio = _to_int_clp(raw.get('precio_unitario_clp'))
        marca = _marca_repuesto_valida(raw.get('marca_repuesto'))
        if precio <= 0 and not marca:
            continue
        proveedor = str(
            raw.get('proveedor_nombre') or raw.get('tienda_ml') or 'Historial del taller',
        ).strip()[:200]
        url = str(raw.get('url_producto') or '').strip()[:500]
        clave = clave_cache_repuesto(
            nombre,
            marca_vehiculo=cotizacion.vehiculo_marca or '',
            modelo_vehiculo=cotizacion.vehiculo_modelo or '',
            anio=cotizacion.vehiculo_anio or '',
        )
        PrecioRepuestoWeb.objects.update_or_create(
            clave=clave,
            dominio=_DOMINIO_HISTORIAL,
            defaults={
                'nombre_producto': nombre[:200],
                'marca_repuesto': marca,
                'precio_clp': precio,
                'tienda': proveedor or 'Historial del taller',
                'url': url,
                'compatibilidad': 'alta',
                'confianza': 0.85,
                'expira_en': expira,
            },
        )
        # También por clave fuzzy corta (match enrich).
        fuzzy = _clave_fuzzy(nombre)
        if fuzzy and fuzzy != clave:
            PrecioRepuestoWeb.objects.update_or_create(
                clave=fuzzy[:240],
                dominio=_DOMINIO_HISTORIAL,
                defaults={
                    'nombre_producto': nombre[:200],
                    'marca_repuesto': marca,
                    'precio_clp': precio,
                    'tienda': proveedor or 'Historial del taller',
                    'url': url,
                    'compatibilidad': 'alta',
                    'confianza': 0.85,
                    'expira_en': expira,
                },
            )
        upserts += 1
    return upserts


def _upsert_plantilla_auto(cotizacion) -> Any | None:
    """Crea/actualiza plantilla automática del taller para marca+modelo+servicio."""
    from mecanimovilapp.apps.ordenes.models import CotizacionCanalPlantilla
    from mecanimovilapp.apps.ordenes.services.cotizacion_canal import snapshot_desde_cotizacion

    marca = (cotizacion.vehiculo_marca or '').strip()
    modelo = (cotizacion.vehiculo_modelo or '').strip()
    servicio = (cotizacion.servicio_nombre or '').strip()
    if not marca or not modelo or not servicio:
        return None

    snap = snapshot_desde_cotizacion(cotizacion)
    snap['aprendizaje_auto'] = True
    snap['cotizacion_origen_id'] = cotizacion.id
    titulo = _titulo_plantilla_auto(marca=marca, modelo=modelo, servicio=servicio)

    existentes = (
        CotizacionCanalPlantilla.objects.filter(taller_id=cotizacion.taller_id)
        .filter(
            Q(titulo=titulo)
            | Q(snapshot__vehiculo_marca__iexact=marca, snapshot__vehiculo_modelo__iexact=modelo),
        )
        .order_by('-actualizado_en')[:20]
    )
    plantilla = None
    for cand in existentes:
        snap_c = cand.snapshot if isinstance(cand.snapshot, dict) else {}
        if not _modelo_coincide(str(snap_c.get('vehiculo_modelo') or ''), modelo):
            continue
        if _norm(str(snap_c.get('vehiculo_marca') or '')) != _norm(marca):
            continue
        if not _servicios_similares(str(snap_c.get('servicio_nombre') or ''), servicio):
            continue
        # Solo reusar plantillas de aprendizaje auto (no pisar plantillas manuales).
        if snap_c.get('aprendizaje_auto') or (cand.titulo or '').startswith('Auto:'):
            plantilla = cand
            break

    if plantilla is None:
        plantilla = CotizacionCanalPlantilla.objects.create(
            taller=cotizacion.taller,
            creado_por=getattr(cotizacion, 'creado_por', None),
            titulo=titulo,
            snapshot=snap,
            uso_count=0,
        )
    else:
        plantilla.titulo = titulo
        plantilla.snapshot = snap
        plantilla.save(update_fields=['titulo', 'snapshot', 'actualizado_en'])
    return plantilla


def registrar_cotizacion_enviada(cotizacion) -> dict[str, Any]:
    """Hook post-envío: plantilla auto + cache de precios por marca/modelo."""
    if cotizacion is None:
        return {'ok': False, 'reason': 'none'}
    try:
        plantilla = _upsert_plantilla_auto(cotizacion)
        upserts = _seed_precios_desde_cotizacion(cotizacion)
        meta = dict(cotizacion.metadata or {})
        meta['aprendizaje_registrado'] = True
        meta['aprendizaje_en'] = timezone.now().isoformat()
        if plantilla is not None:
            meta['plantilla_aprendizaje_id'] = plantilla.id
        cotizacion.metadata = meta
        cotizacion.save(update_fields=['metadata', 'actualizado_en'])
        logger.info(
            'Aprendizaje cotización %s: plantilla=%s precios=%s marca=%s modelo=%s',
            cotizacion.id,
            getattr(plantilla, 'id', None),
            upserts,
            cotizacion.vehiculo_marca,
            cotizacion.vehiculo_modelo,
        )
        return {
            'ok': True,
            'plantilla_id': getattr(plantilla, 'id', None),
            'precios_indexados': upserts,
        }
    except Exception as exc:
        logger.warning(
            'registrar_cotizacion_enviada(%s) falló: %s',
            getattr(cotizacion, 'id', None),
            exc,
            exc_info=True,
        )
        return {'ok': False, 'error': str(exc)}


def construir_bloque_historial_prompt(
    *,
    taller,
    servicio_nombre: str,
    marca: str,
    modelo: str,
    max_cotizaciones: int = 3,
) -> str:
    """Bloque para el prompt Gemini: cotizaciones enviadas previas marca/modelo."""
    if taller is None or not (marca or '').strip() or not (modelo or '').strip():
        return ''
    try:
        from mecanimovilapp.apps.ordenes.models import CotizacionCanal
    except Exception:
        return ''

    desde = timezone.now() - timedelta(days=180)
    qs = (
        CotizacionCanal.objects.filter(
            taller=taller,
            estado__in=('enviada', 'aceptada'),
            creado_en__gte=desde,
        )
        .exclude(vehiculo_marca='')
        .exclude(vehiculo_modelo='')
        .order_by('-enviada_en', '-creado_en')[:40]
    )
    marca_n = _norm(marca)
    lineas: list[str] = []
    for cot in qs:
        if _norm(cot.vehiculo_marca or '') != marca_n:
            continue
        if not _modelo_coincide(cot.vehiculo_modelo or '', modelo):
            continue
        if servicio_nombre and not _servicios_similares(cot.servicio_nombre or '', servicio_nombre):
            # Si no hay servicio pedido, igual listamos; si hay y no match, skip.
            continue
        reps_txt = []
        for raw in (cot.repuestos or [])[:8]:
            if not isinstance(raw, dict):
                continue
            rn = str(raw.get('nombre') or '').strip()
            if not rn:
                continue
            rm = _marca_repuesto_valida(raw.get('marca_repuesto'))
            rp = _to_int_clp(raw.get('precio_unitario_clp'))
            reps_txt.append(
                f'{rn}'
                + (f' ({rm})' if rm else '')
                + (f' ${rp}' if rp else '')
            )
        lineas.append(
            f'- Cotización #{cot.id} {cot.vehiculo_marca} {cot.vehiculo_modelo}: '
            f'servicio="{cot.servicio_nombre}" | mano_obra ${int(cot.mano_obra_clp or 0)} | '
            f'total ${int(cot.total_clp or 0)}'
            + (f' | piezas: {"; ".join(reps_txt)}' if reps_txt else '')
        )
        if len(lineas) >= max_cotizaciones:
            break
    if not lineas:
        return ''
    return (
        'HISTORIAL DEL TALLER PARA ESTE MARCA/MODELO (cotizaciones ya enviadas al cliente; '
        'reutiliza piezas/marcas/precios cuando el servicio sea similar; no inventes otras):\n'
        + '\n'.join(lineas)
    )
