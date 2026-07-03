"""Permisos del asistente de diagnóstico IA."""
from __future__ import annotations


def usuario_puede_usar_asistente_ia(user, *, orden=None, cita=None) -> bool:
    """
    Quién puede consultar/generar guías IA:

    - Mecánico de equipo: solo en órdenes/citas asignadas a él.
    - Mandante (dueño): solo si no hay mecánico asignado (taller unipersonal).
    - Supervisor: nunca.
    - Mecánico domicilio legacy: sus propias órdenes/citas.
    """
    from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

    _taller, miembro, rol = resolver_contexto_taller(user)

    if rol == 'supervisor':
        return False

    if rol == 'mandante':
        if orden is not None:
            return orden.mecanico_asignado_id is None
        if cita is not None:
            return cita.miembro_taller_id is None
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


def filtrar_diagnosticos_asistente_visibles(user, queryset):
    """
    Cada perfil solo ve guías generadas en su propia sesión:
    - Mecánico: generado_por = su MiembroTaller.
    - Mandante (taller unipersonal): generado_por nulo.
    - Mecánico domicilio legacy: generado_por nulo.
    """
    from mecanimovilapp.apps.usuarios.services.taller_contexto import resolver_contexto_taller

    _taller, miembro, rol = resolver_contexto_taller(user)

    if rol == 'mecanico' and miembro is not None:
        return queryset.filter(generado_por_id=miembro.id)

    if rol == 'mandante':
        return queryset.filter(generado_por__isnull=True)

    mecanico_domicilio = getattr(user, 'mecanico_domicilio', None)
    if mecanico_domicilio is not None:
        return queryset.filter(generado_por__isnull=True)

    return queryset.none()
