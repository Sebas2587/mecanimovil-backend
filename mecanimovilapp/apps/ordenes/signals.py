"""
Signals para auditoría y logging en el módulo de órdenes.

Registra automáticamente cambios críticos en el estado y asignación de órdenes
para permitir análisis posterior, trazabilidad y resolución de conflictos.
"""
from django.db.models.signals import pre_save
from django.dispatch import receiver
from mecanimovilapp.apps.ordenes.models import SolicitudServicio, AsignacionTecnicoLog


@receiver(pre_save, sender=SolicitudServicio)
def log_tecnico_assignment(sender, instance, **kwargs):
    """
    Registra cambios en mecanico_asignado antes de guardar.
    Preserva progreso si hay checklist en curso.
    
    Se ejecuta en pre_save (no post_save) para capturar el valor anterior
    antes de que se sobrescriba en la BD.
    
    Casos registrados:
    - Primera asignación: tecnico_anterior=None, tecnico_nuevo=X
    - Reasignación: tecnico_anterior=X, tecnico_nuevo=Y
    - Desasignación: tecnico_anterior=X, tecnico_nuevo=None
    - Sin cambio: no registra nada
    """
    if not instance.pk:
        return
    
    try:
        orden_anterior = SolicitudServicio.objects.get(pk=instance.pk)
    except SolicitudServicio.DoesNotExist:
        return
    
    tecnico_anterior_id = orden_anterior.mecanico_asignado_id
    tecnico_nuevo_id = instance.mecanico_asignado_id
    
    if tecnico_anterior_id == tecnico_nuevo_id:
        return
    
    checklist_en_progreso = False
    progreso_pct = 0
    if hasattr(orden_anterior, 'checklist_instance'):
        checklist = orden_anterior.checklist_instance
        if checklist.estado in ['EN_PROGRESO', 'PAUSADO']:
            checklist_en_progreso = True
            progreso_pct = checklist.progreso_porcentaje
    
    AsignacionTecnicoLog.objects.create(
        orden=instance,
        tecnico_anterior_id=tecnico_anterior_id,
        tecnico_nuevo_id=tecnico_nuevo_id,
        asignado_por=getattr(instance, '_asignado_por_user', None),
        checklist_en_progreso=checklist_en_progreso,
        checklist_progreso_pct=progreso_pct,
    )
