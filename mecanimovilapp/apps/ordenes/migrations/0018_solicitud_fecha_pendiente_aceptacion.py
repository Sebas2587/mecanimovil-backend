from django.db import migrations, models


def backfill_fecha_pendiente_aceptacion(apps, schema_editor):
    SolicitudServicio = apps.get_model('ordenes', 'SolicitudServicio')

    pendientes = SolicitudServicio.objects.filter(
        estado='pendiente_aceptacion_proveedor',
        fecha_pendiente_aceptacion_proveedor__isnull=True,
    )
    for orden in pendientes.iterator(chunk_size=500):
        orden.fecha_pendiente_aceptacion_proveedor = orden.fecha_hora_solicitud
        orden.save(update_fields=['fecha_pendiente_aceptacion_proveedor'])

    respondidas = SolicitudServicio.objects.filter(
        fecha_respuesta_proveedor__isnull=False,
        fecha_pendiente_aceptacion_proveedor__isnull=True,
    )
    for orden in respondidas.iterator(chunk_size=500):
        orden.fecha_pendiente_aceptacion_proveedor = orden.fecha_hora_solicitud
        orden.save(update_fields=['fecha_pendiente_aceptacion_proveedor'])


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0017_solicitud_miembro_preferido_oferta_tecnico'),
    ]

    operations = [
        migrations.AddField(
            model_name='solicitudservicio',
            name='fecha_pendiente_aceptacion_proveedor',
            field=models.DateTimeField(
                blank=True,
                help_text='Inicio del plazo SLA para aceptar o rechazar la orden (24h)',
                null=True,
            ),
        ),
        migrations.RunPython(backfill_fecha_pendiente_aceptacion, migrations.RunPython.noop),
    ]
