"""
Métricas operativas del asistente IA (sin PII ni texto de consultas).
"""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from mecanimovilapp.apps.ordenes.models import OfertaProveedor, PatronAprendizajeNecesidad, SolicitudServicioPublica

from .motor_aprendizaje import contar_patrones_activos


def obtener_resumen_operacion_agendamiento_ia() -> dict[str, Any]:
    """Resumen para operaciones / admin (staff)."""
    ahora = timezone.now()
    desde_30d = ahora - timezone.timedelta(days=30)

    top_patrones = list(
        PatronAprendizajeNecesidad.objects.select_related('servicio')
        .order_by('-confirmaciones', '-ultima_vez')[:8]
        .values(
            'fragmento',
            'confirmaciones',
            'componente_slug',
            'servicio_id',
            'servicio__nombre',
        )
    )
    for row in top_patrones:
        row['servicio_nombre'] = row.pop('servicio__nombre', '') or ''

    solicitudes_estado = {
        row['estado']: row['total']
        for row in SolicitudServicioPublica.objects.filter(
            ofertas__origen='catalogo',
            ofertas__fecha_envio__gte=desde_30d,
        )
        .values('estado')
        .annotate(total=Count('pk', distinct=True))
    }

    return {
        'flags': {
            'agendamiento_ia_asistido': bool(getattr(settings, 'AGENDAMIENTO_IA_ASISTIDO', False)),
            'semantico_enabled': bool(getattr(settings, 'AGENDAMIENTO_IA_SEMANTICO_ENABLED', False)),
            'semantico_proveedor': getattr(settings, 'AGENDAMIENTO_IA_SEMANTICO_PROVEEDOR', 'lexico'),
        },
        'patrones_aprendizaje_activos': contar_patrones_activos(),
        'top_patrones': top_patrones,
        'catalogo_ultimos_30_dias': {
            'ofertas_generadas': OfertaProveedor.objects.filter(
                origen='catalogo',
                fecha_envio__gte=desde_30d,
            ).count(),
            'solicitudes_por_estado': solicitudes_estado,
            'pendiente_confirmacion': SolicitudServicioPublica.objects.filter(
                estado='pendiente_confirmacion',
            ).count(),
        },
        'generado_at': ahora.isoformat(),
    }
