"""Estimados de precio desde trabajos completados del taller (no catálogo)."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from mecanimovilapp.apps.ordenes.models import LineaServicio, SolicitudServicio
from mecanimovilapp.apps.ordenes.services.catalogo_pricing import (
    buscar_oferta_exacta,
    normalizar_nombre_servicio,
    precio_publico_oferta,
    _sin_sufijo_modalidad,
)
from mecanimovilapp.apps.usuarios.models import Taller

MIN_MUESTRAS = 3
MESES_VENTANA = 6


@dataclass(frozen=True)
class EstimadoHistorico:
    servicio_nombre: str
    mediana_clp: int
    min_clp: int
    max_clp: int
    muestras: int
    marca_filtro: str = ''
    modelo_filtro: str = ''


def _formatear_clp(valor: int) -> str:
    return f'${int(valor or 0):,}'.replace(',', '.')


def _nombre_servicio_linea(linea: LineaServicio) -> str:
    oferta = linea.oferta_servicio
    if oferta and getattr(oferta, 'servicio', None):
        return (oferta.servicio.nombre or '').strip()
    return ''


def _linea_coincide_servicio(linea: LineaServicio, nombre_norm: str) -> bool:
    nombre = _nombre_servicio_linea(linea)
    if not nombre:
        return False
    serv_norm = normalizar_nombre_servicio(nombre)
    if not serv_norm:
        return False
    return nombre_norm in serv_norm or serv_norm in nombre_norm


def buscar_estimado_historico(
    *,
    taller: Taller,
    servicio_nombre: str,
    marca: str = '',
    modelo: str = '',
    tipo_motor: str = '',
    min_muestras: int = MIN_MUESTRAS,
) -> EstimadoHistorico | None:
    """Mediana de precios finales en solicitudes completadas (últimos ~6 meses)."""
    if not (marca or '').strip() or not (modelo or '').strip():
        return None
    nombre_norm = normalizar_nombre_servicio(_sin_sufijo_modalidad(servicio_nombre))
    if not nombre_norm:
        return None

    desde = timezone.now() - timedelta(days=MESES_VENTANA * 30)
    qs = (
        LineaServicio.objects.filter(
            solicitud__taller=taller,
            solicitud__estado='completado',
            solicitud__fecha_hora_solicitud__gte=desde,
        )
        .select_related(
            'solicitud',
            'solicitud__vehiculo',
            'solicitud__vehiculo__marca',
            'solicitud__vehiculo__modelo',
            'oferta_servicio',
            'oferta_servicio__servicio',
        )
    )

    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.vehiculo_exacto import (
        vehiculo_historial_identico,
    )

    precios: list[int] = []
    for linea in qs.iterator():
        if not _linea_coincide_servicio(linea, nombre_norm):
            continue
        veh = linea.solicitud.vehiculo
        marca_hist = getattr(getattr(veh, 'marca', None), 'nombre', '') if veh else ''
        modelo_hist = getattr(getattr(veh, 'modelo', None), 'nombre', '') if veh else ''
        if not vehiculo_historial_identico(marca, modelo, marca_hist, modelo_hist):
            continue
        try:
            monto = int(linea.precio_final or linea.precio_unitario or 0)
        except (TypeError, ValueError):
            monto = 0
        if monto > 0:
            precios.append(monto)

    if len(precios) < min_muestras:
        return None

    mediana = int(statistics.median(precios))
    return EstimadoHistorico(
        servicio_nombre=_sin_sufijo_modalidad(servicio_nombre),
        mediana_clp=mediana,
        min_clp=min(precios),
        max_clp=max(precios),
        muestras=len(precios),
        marca_filtro=(marca or '').strip(),
        modelo_filtro=(modelo or '').strip(),
    )


def estimados_historicos_para_datos(
    *,
    taller: Taller,
    servicios: list[str],
    marca: str = '',
    modelo: str = '',
    tipo_motor: str = '',
    permite_estimados: bool = True,
) -> list[EstimadoHistorico]:
    """Solo servicios sin precio de catálogo y con histórico suficiente."""
    if not permite_estimados:
        return []

    out: list[EstimadoHistorico] = []
    vistos: set[str] = set()
    for nombre in servicios:
        clave = normalizar_nombre_servicio(_sin_sufijo_modalidad(nombre))
        if not clave or clave in vistos:
            continue
        vistos.add(clave)

        oferta = buscar_oferta_exacta(
            taller=taller,
            servicio_nombre=nombre,
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
        )
        if oferta:
            precio, _ = precio_publico_oferta(oferta, con_repuestos=True)
            if precio > 0:
                continue

        est = buscar_estimado_historico(
            taller=taller,
            servicio_nombre=nombre,
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
        )
        if est:
            out.append(est)
    return out


def formatear_bloque_historial_precios(estimados: list[EstimadoHistorico]) -> str:
    if not estimados:
        return ''
    lineas = [
        'Referencia histórica de precios (trabajos completados del taller; '
        'NO es tarifa fija ni catálogo — el taller debe confirmar el valor final):',
    ]
    for est in estimados:
        veh = ''
        if est.marca_filtro or est.modelo_filtro:
            partes = ' '.join(p for p in (est.marca_filtro, est.modelo_filtro) if p).strip()
            veh = f' ({partes})' if partes else ''
        rango = ''
        if est.min_clp != est.max_clp:
            rango = f', rango {_formatear_clp(est.min_clp)}–{_formatear_clp(est.max_clp)}'
        lineas.append(
            f'- {est.servicio_nombre}{veh}: mediana {_formatear_clp(est.mediana_clp)} '
            f'(n={est.muestras} casos similares completados){rango}'
        )
    lineas.append(
        'Puedes mencionar la mediana como referencia orientativa ("por casos similares suele rondar…") '
        'pero NUNCA como precio cerrado ni promesa de cotización final.'
    )
    return '\n'.join(lineas)


def tiene_estimado_historico_mencionable(
    *,
    taller: Taller,
    servicios: list[str],
    marca: str = '',
    modelo: str = '',
    tipo_motor: str = '',
    permite_estimados: bool = True,
) -> bool:
    return bool(
        estimados_historicos_para_datos(
            taller=taller,
            servicios=servicios,
            marca=marca,
            modelo=modelo,
            tipo_motor=tipo_motor,
            permite_estimados=permite_estimados,
        )
    )
