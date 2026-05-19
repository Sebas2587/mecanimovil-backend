"""Señales para aprendizaje semántico desde solicitudes confirmadas."""
from django.db import transaction
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from mecanimovilapp.apps.ordenes.models import SolicitudServicioPublica


@receiver(m2m_changed, sender=SolicitudServicioPublica.servicios_solicitados.through)
def aprender_patrones_desde_servicios_solicitud(sender, instance, action, **kwargs):
    if action != 'post_add':
        return
    if not (instance.descripcion_problema or '').strip():
        return

    def _registrar():
        from mecanimovilapp.apps.ordenes.services.agendamiento_ia.motor_aprendizaje import (
            registrar_aprendizaje_desde_solicitud,
        )

        meta = instance.metadata_ia_entrada
        componentes = None
        if isinstance(meta, dict):
            componentes = meta.get('componentes_salud')
        registrar_aprendizaje_desde_solicitud(instance, componentes_salud=componentes)

    transaction.on_commit(_registrar)
