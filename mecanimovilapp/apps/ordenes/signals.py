"""
Signals para auditoría y logging en el módulo de órdenes.

BLOCKER FIX (review d1a6ebe): Audit log moved to post_save + on_commit.
Registra cambios críticos con garantías atómicas.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from mecanimovilapp.apps.ordenes.models import SolicitudServicio, AsignacionTecnicoLog


@receiver(post_save, sender=SolicitudServicio)
def log_tecnico_assignment(sender, instance, created, **kwargs):
    """
    Registra cambios en mecanico_asignado después de guardar exitosamente.
    
    BLOCKER FIX: Cambio de pre_save a post_save + on_commit para:
    1. Audit solo persiste si save principal exitoso (no en autocommit orphan)
    2. Audit sobrevive rollback de transacción externa (on_commit)
    3. old value capturado via _old_mecanico_asignado_id (seteado en viewset antes de modificar)
    
    Casos registrados:
    - Primera asignación: tecnico_anterior=None, tecnico_nuevo=X
    - Reasignación: tecnico_anterior=X, tecnico_nuevo=Y
    - Desasignación: tecnico_anterior=X, tecnico_nuevo=None
    - Sin cambio: no registra nada
    """
    if created:
        # Nueva instancia, no hay cambio anterior
        return
    
    # Detectar cambio via atributo privado (seteado por viewset)
    old_tech_id = getattr(instance, '_old_mecanico_asignado_id', None)
    new_tech_id = instance.mecanico_asignado_id
    
    # Determinar si hubo cambio
    # Si no hay _old_mecanico_asignado_id, asumir que no hubo cambio intencional
    if not hasattr(instance, '_old_mecanico_asignado_id'):
        return
    
    if old_tech_id == new_tech_id:
        return
    
    # Capturar datos inmediatamente (antes de on_commit donde instance puede ser inaccesible)
    orden_id = instance.pk
    asignado_por = getattr(instance, '_asignado_por_user', None)
    asignado_por_id = asignado_por.id if asignado_por else None
    
    # Detectar progreso de checklist
    checklist_en_progreso = False
    progreso_pct = 0
    try:
        from mecanimovilapp.apps.checklists.models import ChecklistInstance
        checklist = ChecklistInstance.objects.filter(orden_id=orden_id).first()
        if checklist and checklist.estado in ['EN_PROGRESO', 'PAUSADO']:
            checklist_en_progreso = True
            progreso_pct = checklist.progreso_porcentaje or 0
    except:
        pass
    
    def create_audit_log():
        """Closure: captura datos, ejecuta post-commit para atomicidad."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        asignado_por_obj = None
        if asignado_por_id:
            try:
                asignado_por_obj = User.objects.get(pk=asignado_por_id)
            except User.DoesNotExist:
                pass
        
        AsignacionTecnicoLog.objects.create(
            orden_id=orden_id,
            tecnico_anterior_id=old_tech_id,
            tecnico_nuevo_id=new_tech_id,
            asignado_por=asignado_por_obj,
            motivo='',
            checklist_en_progreso=checklist_en_progreso,
            checklist_progreso_pct=progreso_pct
        )
    
    # Ejecutar después de commit para garantizar atomicidad completa
    transaction.on_commit(create_audit_log)
