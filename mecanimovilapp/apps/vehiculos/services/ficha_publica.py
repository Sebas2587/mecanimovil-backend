"""Ficha pública compartible de un vehículo (sin datos sensibles)."""
from __future__ import annotations

from mecanimovilapp.apps.ordenes.history_km import kilometraje_al_momento_del_servicio
from mecanimovilapp.apps.ordenes.models import SolicitudServicio
from mecanimovilapp.apps.vehiculos.models_health import ComponenteSaludVehiculo, EstadoSaludVehiculo
from mecanimovilapp.storage.utils import get_image_url


def serializar_ficha_publica_vehiculo(vehiculo, request=None) -> dict:
    """
    Datos seguros para compartir:
    - Identidad visible: marca, modelo, año, cilindraje
    - Salud: score global + componentes (nombre + %)
    - Servicios: nombre, fecha, taller/mecánico (sin costo, VIN, patente, dueño)
    """
    marca = getattr(vehiculo, 'marca_nombre', None) or (
        vehiculo.marca.nombre if getattr(vehiculo, 'marca_id', None) else ''
    )
    modelo = getattr(vehiculo, 'modelo_nombre', None) or (
        vehiculo.modelo.nombre if getattr(vehiculo, 'modelo_id', None) else ''
    )
    anio = getattr(vehiculo, 'year', None)

    snapshot = EstadoSaludVehiculo.objects.filter(vehiculo=vehiculo).first()
    health_score = int(snapshot.salud_general_porcentaje) if snapshot else 0

    componentes = (
        ComponenteSaludVehiculo.objects
        .filter(vehiculo=vehiculo)
        .select_related('componente')
        .order_by('componente__nombre')
    )
    health_details = []
    for comp in componentes:
        if not comp.componente_id:
            continue
        pct = int(comp.salud_porcentaje or 0)
        if pct < 40:
            status = 'critical'
        elif pct < 70:
            status = 'warning'
        else:
            status = 'normal'
        health_details.append({
            'id': comp.componente_id,
            'nombre': comp.componente.nombre,
            'salud_porcentaje': pct,
            'status': status,
        })

    solicitudes = (
        SolicitudServicio.objects
        .filter(vehiculo=vehiculo, estado='completado')
        .select_related('taller', 'mecanico__usuario')
        .prefetch_related('lineas__oferta_servicio__servicio')
        .order_by('-fecha_servicio')[:40]
    )

    servicios = []
    for sol in solicitudes:
        service_name = 'Servicio'
        first_line = sol.lineas.first()
        if first_line and first_line.oferta_servicio_id and first_line.oferta_servicio:
            svc = getattr(first_line.oferta_servicio, 'servicio', None)
            if svc is not None:
                service_name = svc.nombre
            if sol.lineas.count() > 1:
                service_name = f'{service_name} y otros'

        provider_name = 'Proveedor MecaniMovil'
        provider_type = 'taller'
        provider_avatar = None
        provider_id = None

        if sol.taller_id:
            provider_name = sol.taller.nombre or provider_name
            provider_type = 'taller'
            provider_id = sol.taller_id
            foto = getattr(sol.taller, 'foto_perfil', None) or getattr(sol.taller, 'logo', None)
            if foto:
                provider_avatar = get_image_url(foto, request)
        elif sol.mecanico_id:
            u = sol.mecanico.usuario
            provider_name = (
                f'{getattr(u, "first_name", "")} {getattr(u, "last_name", "")}'.strip()
                or provider_name
            )
            provider_type = 'mecanico'
            provider_id = sol.mecanico_id
            if getattr(u, 'foto_perfil', None):
                provider_avatar = get_image_url(u.foto_perfil, request)

        fecha = sol.fecha_servicio.strftime('%d %b %Y') if sol.fecha_servicio else ''
        km = kilometraje_al_momento_del_servicio(sol)

        servicios.append({
            'id': sol.id,
            'servicio_nombre': service_name,
            'fecha': fecha,
            'proveedor_nombre': provider_name,
            'proveedor_tipo': provider_type,
            'proveedor_id': provider_id,
            'proveedor_avatar': provider_avatar,
            # km del servicio es contexto operativo, no identificador sensible
            'kilometraje': km,
        })

    return {
        'id': vehiculo.id,
        'marca': marca or '',
        'modelo': modelo or '',
        'anio': anio,
        'cilindraje': (vehiculo.cilindraje or '').strip(),
        'health_score': health_score,
        'health_details': health_details,
        'servicios': servicios,
        'servicios_count': len(servicios),
        'cta': {
            'titulo': 'Lleva este control en MecaniMovil',
            'descripcion': (
                'Regístrate gratis para guardar la salud de tu auto, '
                'agendar talleres verificados y nunca perder el historial.'
            ),
        },
    }
