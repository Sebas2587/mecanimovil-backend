"""
Ofertas resumidas para cards del home (fase 5 discovery).
Evita N+1: una consulta por tipo de proveedor y lista de IDs.
"""
from collections import defaultdict

from django.db.models import Q

from mecanimovilapp.apps.servicios.models import OfertaServicio
from mecanimovilapp.apps.servicios.oferta_resolucion import resolver_ofertas_preferidas_por_marca
from mecanimovilapp.apps.vehiculos.catalogo_resolver import normalizar_tipo_motor_vehiculo

PANEL_SERVICIOS_DEFAULT_LIMIT = 3


def request_wants_panel_servicios(request) -> bool:
    if request is None:
        return False
    value = str(request.query_params.get('include_panel_servicios', '')).strip().lower()
    return value in ('1', 'true', 'yes', 'on')


def _serialize_panel_item(oferta) -> dict:
    nombre = (oferta.servicio.nombre if oferta.servicio_id else '') or 'Servicio'
    if len(nombre) > 52:
        nombre = f'{nombre[:49]}…'
    precio_pub = float(oferta.precio_publicado_cliente or 0)
    precio_sin = float(oferta.precio_sin_repuestos or 0)
    precio = precio_pub if precio_pub > 0 else precio_sin
    return {
        'servicio_id': oferta.servicio_id,
        'oferta_id': oferta.id,
        'nombre': nombre,
        'precio': precio,
        'precio_publicado_cliente': precio_pub,
        'tipo_servicio': oferta.tipo_servicio or 'sin_repuestos',
        'tipo_motor': getattr(oferta, 'tipo_motor', '') or '',
    }


def fetch_panel_servicios_map(
    tipo_proveedor,
    provider_ids,
    marca_id=None,
    tipo_motor=None,
    limit=None,
):
    """
    Devuelve {proveedor_id: [{servicio_id, nombre, precio, ...}, ...]} ordenado por precio asc.
    """
    limit = limit or PANEL_SERVICIOS_DEFAULT_LIMIT
    if not provider_ids:
        return {}

    qs = OfertaServicio.objects.filter(
        tipo_proveedor=tipo_proveedor,
        disponible=True,
    ).select_related('servicio')

    if tipo_proveedor == 'taller':
        qs = qs.filter(taller_id__in=provider_ids)
    else:
        qs = qs.filter(mecanico_id__in=provider_ids)

    if marca_id:
        qs = qs.filter(
            Q(marca_vehiculo_seleccionada_id=marca_id) | Q(marca_vehiculo_seleccionada__isnull=True)
        )

    if tipo_motor:
        motor = normalizar_tipo_motor_vehiculo(tipo_motor)
        qs = qs.filter(Q(tipo_motor='') | Q(tipo_motor=motor)).filter(
            Q(servicio__tipos_motor_compatibles=[])
            | Q(servicio__tipos_motor_compatibles__contains=[motor])
        )

    ofertas_raw = list(qs)
    if marca_id or tipo_motor:
        ofertas_raw = resolver_ofertas_preferidas_por_marca(
            ofertas_raw, marca_id, tipo_motor=tipo_motor
        )

    ofertas_raw.sort(
        key=lambda o: (
            float(o.precio_publicado_cliente or 0) or float(o.precio_sin_repuestos or 0),
            o.id or 0,
        )
    )

    grouped = defaultdict(list)
    seen_servicio = defaultdict(set)

    for oferta in ofertas_raw:
        pid = oferta.taller_id if tipo_proveedor == 'taller' else oferta.mecanico_id
        if pid is None:
            continue
        sid = oferta.servicio_id
        if sid in seen_servicio[pid]:
            continue
        if len(grouped[pid]) >= limit:
            continue
        seen_servicio[pid].add(sid)
        grouped[pid].append(_serialize_panel_item(oferta))

    return dict(grouped)


def resolve_marca_id_from_request(request):
    """Interpreta query param `marca` (id numérico o nombre)."""
    raw = request.query_params.get('marca') if request else None
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        from mecanimovilapp.apps.vehiculos.models import MarcaVehiculo

        return (
            MarcaVehiculo.objects.filter(nombre__icontains=str(raw).strip())
            .values_list('id', flat=True)
            .first()
        )


def attach_panel_servicios_to_proveedores(
    proveedores,
    tipo_proveedor,
    marca_id=None,
    tipo_motor=None,
    limit=None,
):
    """Adjunta `_panel_servicios_cache` en cada instancia para el serializer."""
    if not proveedores:
        return
    ids = [p.id for p in proveedores]
    by_id = fetch_panel_servicios_map(
        tipo_proveedor,
        ids,
        marca_id=marca_id,
        tipo_motor=tipo_motor,
        limit=limit,
    )
    for prov in proveedores:
        prov._panel_servicios_cache = by_id.get(prov.id, [])
