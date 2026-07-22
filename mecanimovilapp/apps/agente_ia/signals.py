"""Señales para sincronizar conocimiento del taller."""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender='servicios.OfertaServicio')
def sync_oferta_servicio_chunk(sender, instance, **kwargs):
    from mecanimovilapp.apps.agente_ia.tasks import sincronizar_chunk_servicio_task

    if instance.taller_id:
        sincronizar_chunk_servicio_task.delay(instance.id)


@receiver(post_save, sender='ordenes.SolicitudServicio')
def sync_solicitud_historico_chunk(sender, instance, **kwargs):
    from mecanimovilapp.apps.agente_ia.tasks import sincronizar_chunk_historico_task

    if instance.estado == 'completado' and instance.taller_id:
        sincronizar_chunk_historico_task.delay(instance.id)


@receiver(post_save, sender='agente_ia.TallerAgenteConfig')
def sync_instrucciones_taller(sender, instance, **kwargs):
    from mecanimovilapp.apps.agente_ia.tasks import sincronizar_instrucciones_task

    sincronizar_instrucciones_task.delay(instance.taller_id)
