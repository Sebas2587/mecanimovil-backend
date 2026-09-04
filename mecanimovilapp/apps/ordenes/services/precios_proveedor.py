"""Precios propios del taller: upsert, vigencia y candidatos para enrich."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from mecanimovilapp.apps.ordenes.models import (
    PrecioProveedorTaller,
    ProveedorRepuestos,
    _norm_nombre_proveedor,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.categoria_repuesto import (
    categoria_de_repuesto,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.enriquecer_repuestos import (
    _clave_fuzzy,
    _hit,
    _to_int_clp,
)


_CONF_PROVEEDOR = 0.97


def vigencia_dias() -> int:
    return max(1, int(getattr(settings, 'PRECIO_PROVEEDOR_VIGENCIA_DIAS', 90) or 90))


def get_or_create_proveedor(taller, nombre: str, **extra) -> ProveedorRepuestos | None:
    nom = (nombre or '').strip()[:120]
    if taller is None or not nom:
        return None
    norm = _norm_nombre_proveedor(nom)
    if not norm:
        return None
    defaults = {'nombre': nom, 'activo': True}
    defaults.update({k: v for k, v in extra.items() if v not in (None, '')})
    obj, created = ProveedorRepuestos.objects.get_or_create(
        taller=taller,
        nombre_norm=norm,
        defaults=defaults,
    )
    if not created and not obj.activo:
        obj.activo = True
        obj.save(update_fields=['activo', 'actualizado_en'])
    return obj


def upsert_precio_proveedor(
    *,
    taller,
    nombre_repuesto: str,
    precio_clp: int,
    proveedor: ProveedorRepuestos | None = None,
    proveedor_nombre: str = '',
    especificacion: str = '',
    marca_repuesto: str = '',
    codigo_parte: str = '',
    categoria: str = '',
    origen: str = 'manual',
    cotizacion=None,
    precio_referencia_web_clp: int = 0,
    usuario=None,
    vehiculo: dict[str, Any] | None = None,
) -> PrecioProveedorTaller | None:
    if taller is None:
        return None
    precio = _to_int_clp(precio_clp)
    if precio <= 0:
        return None
    nombre = (nombre_repuesto or '').strip()[:200]
    if not nombre:
        return None
    if proveedor is None and proveedor_nombre:
        proveedor = get_or_create_proveedor(taller, proveedor_nombre)
    veh = vehiculo or {}
    if cotizacion is not None and not veh:
        veh = {
            'marca': getattr(cotizacion, 'vehiculo_marca', '') or '',
            'modelo': getattr(cotizacion, 'vehiculo_modelo', '') or '',
            'anio': getattr(cotizacion, 'vehiculo_anio', None),
            'tipo_motor': getattr(cotizacion, 'tipo_motor', '') or '',
            'cilindraje': getattr(cotizacion, 'vehiculo_cilindraje', '') or '',
        }
    cat = categoria or categoria_de_repuesto({'nombre': nombre, 'categoria': categoria})
    with transaction.atomic():
        return PrecioProveedorTaller.objects.create(
            taller=taller,
            proveedor=proveedor,
            clave_fuzzy=_clave_fuzzy(nombre)[:200],
            nombre_repuesto=nombre,
            marca_repuesto=(marca_repuesto or '')[:100],
            codigo_parte=(codigo_parte or '')[:60],
            especificacion=(especificacion or '')[:120],
            categoria=cat[:40],
            precio_clp=precio,
            origen=origen or 'manual',
            cotizacion_origen=cotizacion,
            precio_referencia_web_clp=_to_int_clp(precio_referencia_web_clp),
            registrado_por=usuario,
            vehiculo_marca=str(veh.get('marca') or '')[:80],
            vehiculo_modelo=str(veh.get('modelo') or '')[:80],
            vehiculo_anio=veh.get('anio') or None,
            tipo_motor=str(veh.get('tipo_motor') or '')[:20],
            cilindraje=str(veh.get('cilindraje') or '')[:20],
        )


def _vigente(row: PrecioProveedorTaller, now) -> bool:
    if row.vigente_hasta:
        return row.vigente_hasta > now
    return row.registrado_en >= now - timedelta(days=vigencia_dias())


def candidatos_precio_proveedor(
    taller,
    *,
    marca_vehiculo: str = '',
    modelo_vehiculo: str = '',
    tipo_motor: str = '',
) -> list[dict[str, Any]]:
    if taller is None:
        return []
    try:
        from django.conf import settings as dj_settings

        if not bool(getattr(dj_settings, 'PRECIO_PROVEEDOR_TALLER_ENABLED', False)):
            return []
    except Exception:
        return []
    now = timezone.now()
    qs = (
        PrecioProveedorTaller.objects.filter(taller=taller)
        .select_related('proveedor')
        .order_by('-registrado_en')[:200]
    )
    out: list[dict[str, Any]] = []
    for row in qs:
        vigente = _vigente(row, now)
        if not vigente:
            # Sigue siendo candidato pero referencial (el caller baja certeza).
            pass
        if marca_vehiculo and row.vehiculo_marca:
            if row.vehiculo_marca.strip().lower() != str(marca_vehiculo).strip().lower():
                continue
        if modelo_vehiculo and row.vehiculo_modelo:
            if row.vehiculo_modelo.strip().lower() != str(modelo_vehiculo).strip().lower():
                continue
        proveedor_nombre = ''
        if row.proveedor_id:
            proveedor_nombre = row.proveedor.nombre
        hit = _hit(
            nombre=row.nombre_repuesto,
            marca_repuesto=row.marca_repuesto,
            precio_unitario_clp=int(row.precio_clp or 0),
            fuente_marketplace='proveedor',
            proveedor_nombre=proveedor_nombre,
            confianza=_CONF_PROVEEDOR if vigente else 0.55,
            clave=row.clave_fuzzy,
        )
        hit['proveedor_id'] = row.proveedor_id
        hit['especificacion'] = row.especificacion
        hit['vigente'] = vigente
        out.append(hit)
    return out


def lineas_pendientes_precio(cotizacion) -> list[dict[str, Any]]:
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.resolver_precio import (
        CERTEZA_ASUMIDO,
        CERTEZA_CONFIRMADO,
        backfill_certeza,
    )

    out: list[dict[str, Any]] = []
    for r in cotizacion.repuestos or []:
        if not isinstance(r, dict):
            continue
        certeza = backfill_certeza(r)
        if certeza in (CERTEZA_CONFIRMADO, CERTEZA_ASUMIDO):
            continue
        out.append({
            'id': str(r.get('id') or ''),
            'nombre': str(r.get('nombre') or ''),
            'certeza': certeza,
            'especificacion_pendiente': bool(r.get('especificacion_pendiente')),
        })
    return out


def aplicar_confirmacion_linea(
    cotizacion,
    *,
    repuesto_id: str,
    precio_clp: int,
    proveedor_id: int | None = None,
    proveedor_nombre: str = '',
    especificacion: str = '',
    guardar_en_mis_precios: bool = True,
    usuario=None,
) -> dict[str, Any]:
    reps = list(cotizacion.repuestos or [])
    idx = next(
        (i for i, r in enumerate(reps) if isinstance(r, dict) and str(r.get('id') or '') == str(repuesto_id)),
        None,
    )
    if idx is None:
        raise ValueError('No se encontró el repuesto en la cotización.')
    precio = _to_int_clp(precio_clp)
    if precio <= 0:
        raise ValueError('Indica un precio mayor a cero.')
    linea = dict(reps[idx])
    proveedor = None
    if proveedor_id:
        proveedor = ProveedorRepuestos.objects.filter(
            pk=proveedor_id, taller=cotizacion.taller,
        ).first()
        if proveedor is None:
            raise ValueError('La casa de repuestos no pertenece a este taller.')
    elif proveedor_nombre:
        proveedor = get_or_create_proveedor(cotizacion.taller, proveedor_nombre)
    if especificacion:
        linea['especificacion'] = especificacion[:120]
        linea['especificacion_pendiente'] = False
    linea['precio_unitario_clp'] = precio
    linea['precio_min_clp'] = precio
    linea['precio_max_clp'] = precio
    linea['certeza'] = 'confirmado'
    linea['precio_estimado'] = False
    linea.pop('precio_referencia_mercado', None)
    linea['fuente_marketplace'] = 'proveedor'
    if proveedor is not None:
        linea['proveedor_id'] = proveedor.id
        linea['proveedor_nombre'] = proveedor.nombre
    linea['precio_capturado_en'] = timezone.now().isoformat()
    reps[idx] = linea
    cotizacion.repuestos = reps
    if guardar_en_mis_precios:
        upsert_precio_proveedor(
            taller=cotizacion.taller,
            nombre_repuesto=str(linea.get('nombre') or ''),
            precio_clp=precio,
            proveedor=proveedor,
            especificacion=str(linea.get('especificacion') or ''),
            marca_repuesto=str(linea.get('marca_repuesto') or ''),
            codigo_parte=str(linea.get('codigo_parte') or ''),
            categoria=str(linea.get('categoria') or ''),
            origen='cotizacion_proveedor',
            cotizacion=cotizacion,
            precio_referencia_web_clp=_to_int_clp(linea.get('precio_marketplace_clp')),
            usuario=usuario,
        )
    return linea


def aplicar_asumir_lineas(cotizacion, repuesto_ids: list[str]) -> int:
    ids = {str(i) for i in (repuesto_ids or []) if i}
    reps = list(cotizacion.repuestos or [])
    n = 0
    now = timezone.now().isoformat()
    for i, r in enumerate(reps):
        if not isinstance(r, dict):
            continue
        if ids and str(r.get('id') or '') not in ids:
            continue
        if str(r.get('certeza') or '') in ('confirmado', 'asumido'):
            continue
        techo = _to_int_clp(r.get('precio_max_clp') or r.get('precio_unitario_clp'))
        if techo <= 0:
            continue
        linea = dict(r)
        linea['precio_unitario_clp'] = techo
        linea['precio_max_clp'] = techo
        linea['certeza'] = 'asumido'
        linea['precio_estimado'] = True
        linea['precio_capturado_en'] = now
        reps[i] = linea
        n += 1
    cotizacion.repuestos = reps
    return n
