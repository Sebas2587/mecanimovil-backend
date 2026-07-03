"""Permisos del asistente de diagnóstico IA (solo sesión mecánico)."""
from __future__ import annotations


def usuario_puede_usar_asistente_ia(user, *, orden=None, cita=None) -> bool:
    """
    El asistente IA solo lo operan mecánicos asignados (equipo o domicilio legacy).
    Mandante y supervisor no pueden consultar ni generar guías.
    """
    from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

    _taller, miembro, rol = resolver_contexto_taller(user)

    if rol in ('mandante', 'supervisor'):
        return False

    if rol == 'mecanico' and miembro is not None:
        if orden is not None:
            return orden.mecanico_asignado_id == miembro.id
        if cita is not None:
            return cita.miembro_taller_id == miembro.id
        return False

    mecanico_domicilio = getattr(user, 'mecanico_domicilio', None)
    if mecanico_domicilio is not None:
        if orden is not None:
            return orden.mecanico_id == mecanico_domicilio.id
        if cita is not None:
            return cita.mecanico_id == mecanico_domicilio.id

    return False
