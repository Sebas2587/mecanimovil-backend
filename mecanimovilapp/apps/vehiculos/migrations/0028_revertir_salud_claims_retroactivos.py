"""
Revierte el impacto en salud de reclamos de informes externos (QR).

Los claims previos llamaban actualizar_salud_desde_checklist y anclaban
componentes al km del servicio del taller. Si ese km era mucho menor al
odómetro actual, el HealthEngine degradaba casi todo a ~0–1 %.

A partir de ahora el reclamo solo vincula el informe al historial; esta
migración limpia el daño ya aplicado y recalcula la salud.
"""

from django.db import migrations


def revertir_salud_claims(apps, schema_editor):
    InformeServicioPublico = apps.get_model('checklists', 'InformeServicioPublico')
    ComponenteSaludVehiculo = apps.get_model('vehiculos', 'ComponenteSaludVehiculo')
    EventoSaludVehiculo = apps.get_model('vehiculos', 'EventoSaludVehiculo')

    vehiculo_ids = list(
        InformeServicioPublico.objects.filter(
            reclamado_por_vehiculo_id__isnull=False,
        )
        .values_list('reclamado_por_vehiculo_id', flat=True)
        .distinct()
    )
    if not vehiculo_ids:
        return

    for vehiculo_id in vehiculo_ids:
        checklist_ids = list(
            InformeServicioPublico.objects.filter(
                reclamado_por_vehiculo_id=vehiculo_id,
            ).values_list('checklist_instance_id', flat=True)
        )
        if not checklist_ids:
            continue

        comp_ids = set(
            EventoSaludVehiculo.objects.filter(
                vehiculo_id=vehiculo_id,
                checklist_id__in=checklist_ids,
            ).values_list('componente_id', flat=True)
        )

        # También eventos ya etiquetados como claim retroactivo (metadata JSON).
        for ev in EventoSaludVehiculo.objects.filter(vehiculo_id=vehiculo_id).iterator():
            meta = ev.metadata or {}
            if meta.get('origen') == 'CLAIM_RETROACTIVO':
                comp_ids.add(ev.componente_id)

        if not comp_ids:
            # Fallback: cualquier ancla CHECKLIST de este vehículo sin historial
            # de solicitud in-app (solo aplica a autos dañados por el claim).
            qs = ComponenteSaludVehiculo.objects.filter(
                vehiculo_id=vehiculo_id,
                historial_fuente='CHECKLIST',
            )
        else:
            qs = ComponenteSaludVehiculo.objects.filter(
                vehiculo_id=vehiculo_id,
                componente_id__in=comp_ids,
                historial_fuente='CHECKLIST',
            )

        qs.update(
            historial_conocido=False,
            historial_fuente='ENGINE',
            km_ultimo_servicio=0,
            salud_anclada_pct=None,
            fecha_ultimo_servicio=None,
            mensaje_alerta='',
            requiere_servicio_inmediato=False,
        )

        # Excluir eventos del claim del dataset ML (no borrar auditoría).
        for ev in EventoSaludVehiculo.objects.filter(
            vehiculo_id=vehiculo_id,
            checklist_id__in=checklist_ids,
        ):
            meta = dict(ev.metadata or {})
            meta['excluido_entrenamiento'] = True
            meta['motivo_exclusion'] = 'CLAIM_RETROACTIVO_NO_AFECTA_DEGRADACION'
            meta['origen'] = meta.get('origen') or 'CLAIM_RETROACTIVO'
            ev.metadata = meta
            ev.save(update_fields=['metadata'])

    # Recalcular con el engine real (no el historical apps.get_model).
    try:
        from mecanimovilapp.apps.vehiculos.services.health_engine import HealthEngine

        for vehiculo_id in vehiculo_ids:
            try:
                HealthEngine.calcular_salud_vehiculo(vehiculo_id)
            except Exception:
                pass
    except Exception:
        pass


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0027_ensure_eventosaludvehiculo_indexes'),
        ('checklists', '0008_informe_publico_firma_supervisor'),
    ]

    operations = [
        migrations.RunPython(revertir_salud_claims, noop_reverse),
    ]
