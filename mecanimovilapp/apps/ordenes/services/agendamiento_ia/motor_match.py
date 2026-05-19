"""
Matching de hasta 3 candidatos desde OfertaServicio (stateless).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Q

from mecanimovilapp.apps.personalizacion.ml_engine import MotorRecomendaciones
from mecanimovilapp.apps.servicios.models import OfertaServicio
from mecanimovilapp.apps.usuarios.models import MechanicServiceArea, MecanicoDomicilio, Taller
from mecanimovilapp.apps.vehiculos.models import Vehiculo

MAX_CANDIDATOS = 3


def _proveedor_usuario(oferta: OfertaServicio):
    if oferta.tipo_proveedor == 'taller' and oferta.taller_id:
        return oferta.taller.usuario_id, oferta.taller
    if oferta.tipo_proveedor == 'mecanico' and oferta.mecanico_id:
        return oferta.mecanico.usuario_id, oferta.mecanico
    return None, None


def _mecanico_cubre_comunas(mecanico_id: int, comunas: list[str]) -> bool:
    if not comunas:
        return True
    comunas_norm = {c.strip().lower() for c in comunas if c and str(c).strip()}
    if not comunas_norm:
        return True
    areas = MechanicServiceArea.objects.filter(
        mechanic_id=mecanico_id,
        is_active=True,
    )
    for area in areas:
        names = area.commune_names or []
        for name in names:
            if str(name).strip().lower() in comunas_norm:
                return True
    return False


def _build_desglose(oferta: OfertaServicio, requiere_repuestos: bool) -> dict[str, Any]:
    mo = float(oferta.costo_mano_de_obra_sin_iva or 0)
    rep = float(oferta.costo_repuestos_sin_iva or 0)
    gest = float(oferta.costo_gestion_compra_sin_iva or 0) if requiere_repuestos else 0.0
    total = float(oferta.precio_publicado_cliente or 0)
    if total <= 0:
        total = float(
            oferta.precio_con_repuestos if requiere_repuestos else oferta.precio_sin_repuestos
        )
    return {
        'mano_obra': mo,
        'repuestos': rep,
        'gestion': gest,
        'precio_publicado_cliente': total,
    }


def _serialize_candidato(
    oferta: OfertaServicio,
    score: float,
    explicacion: str,
    requiere_repuestos: bool,
) -> dict[str, Any]:
    usuario_id, proveedor = _proveedor_usuario(oferta)
    nombre = ''
    rating = 0.0
    a_domicilio = oferta.tipo_proveedor == 'mecanico'

    if proveedor:
        nombre = getattr(proveedor, 'nombre', None) or str(proveedor)
        rating = float(getattr(proveedor, 'calificacion_promedio', 0) or 0)

    precio_rep = float(oferta.precio_con_repuestos or 0)
    precio_sin = float(oferta.precio_sin_repuestos or 0)

    return {
        'oferta_servicio_id': oferta.id,
        'proveedor': {
            'usuario_id': str(usuario_id) if usuario_id else None,
            'nombre': nombre,
            'tipo': oferta.tipo_proveedor,
            'rating': rating,
        },
        'servicio': {
            'id': oferta.servicio_id,
            'nombre': oferta.servicio.nombre if oferta.servicio_id else '',
        },
        'precio_con_repuestos': precio_rep,
        'precio_sin_repuestos': precio_sin,
        'incluye_repuestos_sugerido': requiere_repuestos,
        'a_domicilio': a_domicilio,
        'desglose': _build_desglose(oferta, requiere_repuestos),
        'score_match': round(score, 3),
        'explicacion': explicacion,
    }


def listar_candidatos_proveedor(
    *,
    vehiculo_id: int,
    servicio_ids: list[int],
    requiere_repuestos: bool = True,
    comunas_extraidas: list[str] | None = None,
    lat: float | None = None,
    lng: float | None = None,
) -> dict[str, Any]:
    """Stateless: no persiste consulta."""
    vehiculo = (
        Vehiculo.objects.select_related('marca', 'modelo')
        .filter(pk=vehiculo_id)
        .first()
    )
    if not vehiculo:
        return {'candidatos': [], 'error': 'vehiculo_no_encontrado'}

    if not servicio_ids:
        return {'candidatos': []}

    marca = vehiculo.marca
    qs = (
        OfertaServicio.objects.filter(
            servicio_id__in=servicio_ids,
            disponible=True,
        )
        .filter(
            Q(marca_vehiculo_seleccionada__isnull=True)
            | Q(marca_vehiculo_seleccionada=marca)
            if marca
            else Q()
        )
        .select_related(
            'servicio',
            'taller',
            'taller__usuario',
            'mecanico',
            'mecanico__usuario',
        )
    )

    filtered: list[OfertaServicio] = []
    comunas = comunas_extraidas or []

    for oferta in qs:
        if oferta.tipo_proveedor == 'taller' and oferta.taller_id:
            t = oferta.taller
            if not (t.verificado and t.activo):
                continue
            if marca and not t.marcas_atendidas.filter(pk=marca.pk).exists():
                continue
            filtered.append(oferta)
        elif oferta.tipo_proveedor == 'mecanico' and oferta.mecanico_id:
            m = oferta.mecanico
            if not (m.verificado and m.activo):
                continue
            if marca and not m.marcas_atendidas.filter(pk=marca.pk).exists():
                continue
            if not _mecanico_cubre_comunas(m.id, comunas):
                continue
            filtered.append(oferta)

    if not filtered:
        return {'candidatos': []}

    motor = MotorRecomendaciones()
    try:
        ordered = motor.ordenar_por_relevancia(
            OfertaServicio.objects.filter(
                id__in=[o.id for o in filtered]
            ).select_related(
                'servicio', 'taller', 'mecanico', 'taller__usuario', 'mecanico__usuario'
            ),
            vehiculo,
        )
        if isinstance(ordered, list):
            pool = ordered
        else:
            pool = list(ordered)
    except Exception:
        pool = filtered

    # Un proveedor por candidato (mejor oferta por usuario proveedor)
    seen_proveedores: set = set()
    candidatos: list[dict[str, Any]] = []

    for oferta in pool:
        uid, _ = _proveedor_usuario(oferta)
        if not uid or uid in seen_proveedores:
            continue
        seen_proveedores.add(uid)
        rating = float(
            getattr(oferta.taller or oferta.mecanico, 'calificacion_promedio', 0) or 0
        )
        score = 0.4 + 0.1 * (rating / 5.0)
        candidatos.append(
            _serialize_candidato(
                oferta,
                score,
                'Ofrece el servicio para tu vehículo y zona',
                requiere_repuestos,
            )
        )
        if len(candidatos) >= MAX_CANDIDATOS:
            break

    return {'candidatos': candidatos}
