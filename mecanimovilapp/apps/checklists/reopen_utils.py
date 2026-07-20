"""
Utilidades compartidas para reabrir un ChecklistInstance y permitir al proveedor
volver a completarlo (p. ej. cuando las fotos de evidencia no se subieron).
"""
from __future__ import annotations

FOTO_TEXT_PATTERNS = ('foto(s) de evidencia', 'fotos de evidencia', 'foto de evidencia')

# Estados del checklist que se pueden reabrir
ESTADOS_CHECKLIST_REABRIR = (
    'COMPLETADO',
    'PENDIENTE_FIRMA_CLIENTE',
    'EN_PROGRESO',
    'PAUSADO',
    'PENDIENTE',
)

# Orden en flujo avanzado pero checklist desincronizado (repair)
ESTADOS_ORDEN_REPARAR = (
    'pendiente_firma_cliente',
    'checklist_completado',
    'completado',
    'confirmado',
)


def es_texto_foto_evidencia(texto) -> bool:
    if not texto:
        return False
    t = str(texto).lower().strip()
    partes = t.split()
    return bool(partes and partes[0].isdigit() and any(p in t for p in FOTO_TEXT_PATTERNS))


def nombre_cliente_orden(orden) -> str:
    """Nombre legible del cliente para admin/listados (carrito legacy o FK directa)."""
    try:
        if getattr(orden, 'cliente', None) and orden.cliente.usuario:
            return orden.cliente.usuario.get_full_name() or orden.cliente.usuario.username
    except Exception:
        pass
    return 'Cliente'


def puede_reabrir_checklist(instance, orden) -> tuple[bool, str]:
    if instance.estado == 'CANCELADO':
        return False, 'El checklist está cancelado.'
    if instance.estado in ESTADOS_CHECKLIST_REABRIR:
        return True, ''
    return False, f'Estado "{instance.estado}" no admite reapertura.'


def reabrir_checklist_instance(
    instance,
    *,
    reset_todas_respuestas: bool = False,
    forzar: bool = False,
) -> dict:
    """
    Reabre un checklist: EN_PROGRESO, limpia firmas/fotos y alinea la orden.

    Returns dict con métricas para logging/admin.
    """
    from mecanimovilapp.apps.checklists.models import ChecklistPhoto

    orden = instance.orden
    ok, motivo = puede_reabrir_checklist(instance, orden)
    if not ok and not forzar:
        raise ValueError(motivo)

    if instance.estado == 'CANCELADO' and not forzar:
        raise ValueError('No se puede reabrir un checklist cancelado.')

    respuestas = list(
        instance.respuestas.select_related('item_template__catalog_item').all()
    )
    fotos_qs = ChecklistPhoto.objects.filter(response__checklist_instance=instance)
    fotos_count = fotos_qs.count()

    if reset_todas_respuestas:
        targets = respuestas
    else:
        targets = [
            r for r in respuestas
            if r.item_template.catalog_item.tipo_pregunta == 'PHOTO'
            or es_texto_foto_evidencia(r.respuesta_texto)
        ]

    for r in targets:
        r.completado = False
        update_fields = ['completado']
        if es_texto_foto_evidencia(r.respuesta_texto):
            r.respuesta_texto = ''
            update_fields.append('respuesta_texto')
        elif reset_todas_respuestas:
            r.respuesta_texto = ''
            r.respuesta_numero = None
            r.respuesta_booleana = None
            r.respuesta_seleccion = None
            r.respuesta_fecha = None
            update_fields.extend([
                'respuesta_texto', 'respuesta_numero',
                'respuesta_booleana', 'respuesta_seleccion', 'respuesta_fecha',
            ])
        r.save(update_fields=update_fields)

    total = len(respuestas)
    completadas = sum(1 for r in respuestas if r.completado)
    progreso = int((completadas / total) * 100) if total > 0 else 0

    fotos_eliminadas, _ = fotos_qs.delete()

    instance.estado = 'EN_PROGRESO'
    instance.firma_tecnico = None
    instance.firma_cliente = None
    instance.firma_supervisor = None
    instance.firma_supervisor_por = None
    instance.fecha_firma_supervisor = None
    instance.fecha_finalizacion = None
    instance.progreso_porcentaje = progreso
    if not instance.fecha_inicio:
        from django.utils import timezone
        instance.fecha_inicio = timezone.now()
    instance.save(update_fields=[
        'estado', 'firma_tecnico', 'firma_cliente',
        'firma_supervisor', 'firma_supervisor_por', 'fecha_firma_supervisor',
        'fecha_finalizacion', 'progreso_porcentaje', 'fecha_inicio',
    ])

    orden_actualizada = False
    if orden.estado in ESTADOS_ORDEN_REPARAR:
        orden.estado = 'checklist_en_progreso'
        orden.save(update_fields=['estado'])
        orden_actualizada = True

    return {
        'progreso': progreso,
        'completadas': completadas,
        'total_respuestas': total,
        'respuestas_reseteadas': len(targets),
        'fotos_eliminadas': fotos_eliminadas,
        'fotos_count_antes': fotos_count,
        'orden_actualizada': orden_actualizada,
        'orden_estado_nuevo': orden.estado,
    }
