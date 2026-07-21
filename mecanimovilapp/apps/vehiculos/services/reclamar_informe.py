"""
Reclamo de informe público: vincula checklist oficial a Vehiculo del cliente.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from mecanimovilapp.apps.checklists.models_informe import InformeServicioPublico
from mecanimovilapp.apps.vehiculos.kilometraje_validation import validar_kilometraje_usuario
from mecanimovilapp.apps.vehiculos.models import Vehiculo

logger = logging.getLogger(__name__)


def _normalizar_patente(patente: str) -> str:
    return (patente or '').strip().upper().replace('-', '').replace(' ', '')


def reclamar_informe_por_token(token: str, cliente) -> dict:
    """
    Vincula el servicio del informe al vehículo del cliente autenticado.
    Retorna dict con success/message/data o lanza ValueError con mensaje.
    """
    try:
        informe = InformeServicioPublico.objects.select_related(
            'checklist_instance',
            'checklist_instance__cita_personal',
            'reclamado_por_vehiculo',
        ).get(token=token)
    except InformeServicioPublico.DoesNotExist:
        raise ValueError('Informe no encontrado')

    if informe.reclamado_por_vehiculo_id:
        if informe.reclamado_por_cliente_id == cliente.id:
            return {
                'success': True,
                'already_claimed': True,
                'vehiculo_id': informe.reclamado_por_vehiculo_id,
                'message': 'Este servicio ya está vinculado a tu vehículo.',
            }
        raise ValueError('Este informe ya fue reclamado por otro usuario')

    patente_informe = _normalizar_patente(informe.vehiculo_patente)
    if not patente_informe:
        raise ValueError('El informe no tiene patente asociada')

    vehiculo = (
        Vehiculo.objects.filter(cliente=cliente)
        .extra(where=["UPPER(REPLACE(REPLACE(patente, '-', ''), ' ', '')) = %s"], params=[patente_informe])
        .first()
    )
    if vehiculo is None:
        vehiculo = Vehiculo.objects.filter(patente__iexact=patente_informe, cliente=cliente).first()

    if vehiculo is None:
        raise ValueError(
            'Primero registra tu vehículo con la patente del informe; '
            'luego escanea el QR nuevamente para vincular el servicio.'
        )

    otro = Vehiculo.objects.filter(patente__iexact=vehiculo.patente).exclude(cliente=cliente).exists()
    if otro:
        raise ValueError('Esta patente ya está registrada por otro usuario en Mecanimovil')

    km_usuario = int(vehiculo.kilometraje or 0)
    km_api = informe.kilometraje_api or vehiculo.kilometraje_api
    validacion = validar_kilometraje_usuario(
        kilometraje_usuario=km_usuario,
        mileage_sii=km_api,
        year=vehiculo.year or informe.vehiculo_anio,
    )
    if not validacion.get('valid', True) and validacion.get('nivel') == 'error':
        raise ValueError(validacion.get('mensaje') or 'Kilometraje no válido respecto a los datos oficiales')

    checklist = informe.checklist_instance
    checklist_id = checklist.id
    vehicle_id = vehiculo.id
    # Anclar al odómetro ACTUAL del vehículo (no al km del taller). Así el %
    # declarado en el checklist se refleja en salud sin degradar por la diferencia
    # entre km del servicio (p.ej. 63.000) y km al registrar (p.ej. 148.000).
    km_ancla = int(vehiculo.kilometraje or 0) or None

    with transaction.atomic():
        from mecanimovilapp.apps.vehiculos.tasks import actualizar_salud_desde_checklist

        try:
            actualizar_salud_desde_checklist(
                checklist_id,
                vehicle_id,
                km_servicio_override=km_ancla,
                fecha_servicio_override=timezone.now(),
                actualizar_odometro=False,
            )
        except Exception as exc:
            logger.error('Error aplicando salud desde reclamo informe %s: %s', token, exc, exc_info=True)
            raise ValueError('No se pudo registrar el impacto del servicio en tu vehículo') from exc

        _dedupe_eventos_ml_declarados(vehiculo.id, checklist_id)
        _tag_eventos_claim_retroactivo(vehiculo.id, checklist_id)

        informe.reclamado_por_vehiculo = vehiculo
        informe.reclamado_por_cliente = cliente
        informe.reclamado_en = timezone.now()
        informe.estado = 'VEHICULO_RECLAMADO'
        informe.save(
            update_fields=[
                'reclamado_por_vehiculo',
                'reclamado_por_cliente',
                'reclamado_en',
                'estado',
            ]
        )

    return {
        'success': True,
        'vehiculo_id': vehiculo.id,
        'checklist_id': checklist_id,
        'message': 'Servicio vinculado. La salud se actualizó con lo inspeccionado en el taller.',
        'componentes_oficiales': _componentes_desde_checklist(checklist),
        'salud_actualizada': True,
    }


def _componentes_desde_checklist(checklist) -> list[dict]:
    """IDs/nombres de componentes actualizados por el checklist (para UI read-only)."""
    from mecanimovilapp.apps.vehiculos.tasks import _candidatos_por_componente

    candidatos = _candidatos_por_componente(
        list(checklist.respuestas.select_related('item_template__catalog_item').all())
    )
    out = []
    for comp_id, _data in candidatos.items():
        try:
            from mecanimovilapp.apps.vehiculos.models_health import ComponenteSalud

            comp = ComponenteSalud.objects.filter(id=comp_id).first()
            if comp:
                out.append({'id': comp.id, 'nombre': comp.nombre})
        except Exception:
            continue
    return out


def _tag_eventos_claim_retroactivo(vehiculo_id: int, checklist_id: int) -> None:
    """Marca eventos creados por el reclamo con origen CLAIM_RETROACTIVO."""
    try:
        from mecanimovilapp.apps.vehiculos.models_health import EventoSaludVehiculo

        for ev in EventoSaludVehiculo.objects.filter(
            vehiculo_id=vehiculo_id,
            checklist_id=checklist_id,
        ):
            meta = dict(ev.metadata or {})
            if meta.get('origen') == 'CLAIM_RETROACTIVO':
                continue
            meta['origen'] = 'CLAIM_RETROACTIVO'
            ev.metadata = meta
            ev.save(update_fields=['metadata'])
    except Exception as exc:
        logger.warning('tag CLAIM_RETROACTIVO falló vehículo %s: %s', vehiculo_id, exc)


def _dedupe_eventos_ml_declarados(vehiculo_id: int, checklist_id: int) -> None:
    """
    Marca eventos USUARIO_DECLARADO conflictivos para excluirlos del entrenamiento ML.
    No borra datos; agrega metadata de exclusión.
    """
    try:
        from mecanimovilapp.apps.vehiculos.models_health import EventoSaludVehiculo

        ventana = timezone.now() - timedelta(days=45)
        EventoSaludVehiculo.objects.filter(
            vehiculo_id=vehiculo_id,
            metadata__fuente='USUARIO_DECLARADO',
            fecha_evento__gte=ventana,
        ).update(
            metadata={
                'fuente': 'USUARIO_DECLARADO',
                'excluido_entrenamiento': True,
                'motivo_exclusion': 'SUPERSEDED_BY_CLAIM_RETROACTIVO',
                'checklist_reclamado_id': checklist_id,
            }
        )
    except Exception as exc:
        logger.warning('dedupe ML declarados falló vehículo %s: %s', vehiculo_id, exc)
