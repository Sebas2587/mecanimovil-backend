"""
Kilometraje asociado a una solicitud completada (momento del servicio).
"""
from django.core.exceptions import ObjectDoesNotExist


def kilometraje_al_momento_del_servicio(solicitud):
    """
    Retorna el km registrado en el checklist al completar la orden, o None si no aplica.
    No usa el odómetro actual del vehículo (ese valor puede haber cambiado después).
    """
    try:
        ci = solicitud.checklist_instance
    except ObjectDoesNotExist:
        ci = None
    if not ci or ci.estado != 'COMPLETADO':
        return None
    from mecanimovilapp.apps.checklists.km_extraction import extraer_kilometraje_desde_checklist_instance
    return extraer_kilometraje_desde_checklist_instance(ci)
