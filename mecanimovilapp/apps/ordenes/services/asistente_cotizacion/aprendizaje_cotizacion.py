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


def buscar_plantilla_reutilizable(
    *,
    taller,
    marca: str,
    modelo: str,
    servicio_nombre: str,
    cilindraje: str = '',
):
    """Plantilla (manual o Auto:) del taller para mismo vehículo + servicio similar.

    Prioriza plantillas de aprendizaje (`aprendizaje_auto`) y luego manuales.
    Devuelve CotizacionCanalPlantilla o None.
    """
    if taller is None or not (marca or '').strip() or not (modelo or '').strip():
        return None
    if not (servicio_nombre or '').strip():
        return None
    try:
        from mecanimovilapp.apps.ordenes.models import CotizacionCanalPlantilla
        from mecanimovilapp.apps.ordenes.services.plantilla_vehiculo import (
            filtrar_plantillas_por_vehiculo,
        )
    except Exception:
        return None

    qs = CotizacionCanalPlantilla.objects.filter(taller=taller).order_by('-actualizado_en')
    candidatas = list(
        filtrar_plantillas_por_vehiculo(
            qs,
            marca=marca,
            modelo=modelo,
            cilindraje=cilindraje or '',
        )[:40]
    )
    if not candidatas:
        # Fallback: filtro laxo por marca/modelo en snapshot.
        marca_n = _norm(marca)
        candidatas = []
        for p in qs[:60]:
            snap = p.snapshot if isinstance(p.snapshot, dict) else {}
            if _norm(str(snap.get('vehiculo_marca') or '')) != marca_n:
                continue
            if not _modelo_coincide(str(snap.get('vehiculo_modelo') or ''), modelo):
                continue
            candidatas.append(p)

    mejores_auto = []
    mejores_manual = []
    for p in candidatas:
        snap = p.snapshot if isinstance(p.snapshot, dict) else {}
        serv_p = str(snap.get('servicio_nombre') or p.titulo or '')
        # Quitar prefijo "Auto: … — " del título si el snapshot no trae servicio.
        if not snap.get('servicio_nombre') and (p.titulo or '').startswith('Auto:'):
            partes = (p.titulo or '').split('—', 1)
            if len(partes) == 2:
                serv_p = partes[1].strip()
        if not _servicios_similares(serv_p, servicio_nombre):
            continue
        reps = snap.get('repuestos') or []
        if not isinstance(reps, list) or not reps:
            continue
        # Requiere al menos un precio o marca aprendida para valer la pena.
        util = any(
            isinstance(r, dict)
            and (
                _to_int_clp(r.get('precio_unitario_clp')) > 0
                or _marca_repuesto_valida(r.get('marca_repuesto'))
                or str(r.get('proveedor_nombre') or '').strip()
            )
            for r in reps
        )
        if not util:
            continue
        es_auto = bool(snap.get('aprendizaje_auto')) or (p.titulo or '').startswith('Auto:')
        (mejores_auto if es_auto else mejores_manual).append(p)

    return (mejores_auto or mejores_manual or [None])[0]


def plantilla_tiene_cobertura_precios(plantilla) -> bool:
    """True si la plantilla trae precios usables en la mayoría de líneas."""
    if plantilla is None:
        return False
    snap = plantilla.snapshot if isinstance(plantilla.snapshot, dict) else {}
    reps = snap.get('repuestos') or []
    if not isinstance(reps, list) or not reps:
        return False
    con_precio = sum(
        1 for r in reps if isinstance(r, dict) and _to_int_clp(r.get('precio_unitario_clp')) > 0
    )
    return con_precio >= max(1, (len(reps) + 1) // 2)


def puede_omitir_busqueda_web(cotizacion) -> bool:
    """True si no hace falta Tavily: historial/catálogo/cache cubren las líneas.

    Criterios (cualquiera):
    - origen plantilla / reutilizado_historial
    - todas las líneas candidatas ya tienen fuente catalogo/historial
    - PrecioRepuestoWeb vigente para todos los nombres que faltan
    - existe plantilla aprendizaje mismo modelo+servicio con cobertura de precios
    """
    if cotizacion is None:
        return False
    meta = cotizacion.metadata if isinstance(cotizacion.metadata, dict) else {}
    origen = str(meta.get('origen') or '')
    if origen in ('plantilla', 'plantilla_auto', 'reutilizado_historial', 'catalogo_taller'):
        return True
    if meta.get('precio_desde_catalogo') and not meta.get('precio_parcial_catalogo'):
        return True

    reps = list(cotizacion.repuestos or [])
    if not reps:
        # Mano de obra sola desde catálogo (sin repuestos) también omite web.
        return bool(meta.get('precio_desde_catalogo'))

    candidatos = []
    for rep in reps:
        if not isinstance(rep, dict):
            continue
        fuente = str(rep.get('fuente_marketplace') or '').strip()
        if fuente in ('catalogo', 'historial'):
            continue
        necesita = (
            bool(rep.get('precio_estimado', True))
            or not str(rep.get('marca_repuesto') or '').strip()
            or not str(rep.get('proveedor_nombre') or '').strip()
        )
        if necesita:
            candidatos.append(rep)

    if not candidatos:
        return True

    try:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.busqueda_web_repuestos import (
            nombres_sin_cache_vigente,
        )
    except Exception:
        nombres_sin_cache_vigente = None

    if nombres_sin_cache_vigente is not None:
        nombres = [
            str(r.get('nombre') or '').strip() for r in candidatos if str(r.get('nombre') or '').strip()
        ]
        faltantes, _hits = nombres_sin_cache_vigente(
            nombres,
            marca_vehiculo=getattr(cotizacion, 'vehiculo_marca', '') or '',
            modelo_vehiculo=getattr(cotizacion, 'vehiculo_modelo', '') or '',
            anio=getattr(cotizacion, 'vehiculo_anio', '') or '',
        )
        if not faltantes:
            return True

    plantilla = buscar_plantilla_reutilizable(
        taller=getattr(cotizacion, 'taller', None),
        marca=getattr(cotizacion, 'vehiculo_marca', '') or '',
        modelo=getattr(cotizacion, 'vehiculo_modelo', '') or '',
        servicio_nombre=getattr(cotizacion, 'servicio_nombre', '') or '',
        cilindraje=getattr(cotizacion, 'vehiculo_cilindraje', '') or '',
    )
    return plantilla_tiene_cobertura_precios(plantilla)


def marcar_omitir_busqueda_web(cotizacion, *, motivo: str = 'historial') -> Any:
    """Marca la cotización para no gastar Tavily/Gemini url_context."""
    if cotizacion is None:
        return cotizacion
    meta = dict(cotizacion.metadata or {})
    meta['busqueda_web_estado'] = f'omitida_{motivo}'[:40]
    meta['busqueda_web_en'] = timezone.now().isoformat()
    cotizacion.metadata = meta
    try:
        cotizacion.save(update_fields=['metadata', 'actualizado_en'])
    except Exception:
        pass
    return cotizacion


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
