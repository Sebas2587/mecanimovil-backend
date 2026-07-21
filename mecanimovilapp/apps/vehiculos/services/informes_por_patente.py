"""
Listado y conteo de informes públicos pendientes de reclamar por patente.
"""

from __future__ import annotations

from mecanimovilapp.apps.checklists.models_informe import InformeServicioPublico
from mecanimovilapp.apps.vehiculos.services.reclamar_informe import _normalizar_patente


def _query_informes_pendientes_por_patente(patente: str):
    patente_norm = _normalizar_patente(patente)
    if not patente_norm:
        return InformeServicioPublico.objects.none()

    return (
        InformeServicioPublico.objects.filter(
            reclamado_por_vehiculo__isnull=True,
            estado='FIRMADO',
        )
        .select_related(
            'checklist_instance',
            'checklist_instance__cita_personal',
            'checklist_instance__cita_personal__taller',
        )
        .extra(
            where=["UPPER(REPLACE(REPLACE(vehiculo_patente, '-', ''), ' ', '')) = %s"],
            params=[patente_norm],
        )
        .order_by('-generado_en')
    )


def _taller_nombre(informe: InformeServicioPublico) -> str:
    checklist = getattr(informe, 'checklist_instance', None)
    if not checklist:
        return ''
    cita = getattr(checklist, 'cita_personal', None)
    if not cita or not cita.taller_id:
        return ''
    return getattr(cita.taller, 'nombre', '') or ''


def _serializar_informe_pendiente(informe: InformeServicioPublico) -> dict:
    """
    Resumen público para UI de registro.
    No incluye token: el vínculo solo es posible con QR/enlace del informe.
    """
    fecha = informe.fecha_firma_cliente or informe.generado_en
    return {
        'id': informe.id,
        'taller_nombre': _taller_nombre(informe),
        'fecha_servicio': fecha.isoformat() if fecha else None,
        'kilometraje_servicio': informe.kilometraje_servicio,
        'vehiculo_marca': informe.vehiculo_marca or '',
        'vehiculo_modelo': informe.vehiculo_modelo or '',
        'vehiculo_anio': informe.vehiculo_anio,
        'resumen_corto': (informe.resumen_ia or '')[:200],
    }


def listar_informes_pendientes_por_patente(patente: str) -> list[dict]:
    """Informes firmados y no reclamados (sin tokens) para la patente normalizada."""
    qs = _query_informes_pendientes_por_patente(patente)
    return [_serializar_informe_pendiente(informe) for informe in qs]


def contar_informes_pendientes_por_patente(patente: str) -> int:
    """Conteo para teaser público (sin exponer tokens)."""
    return _query_informes_pendientes_por_patente(patente).count()
