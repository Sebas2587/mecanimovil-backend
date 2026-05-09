"""
Estado intermedio pendiente_firma_cliente en SolicitudServicio para soportar
firma diferida del cliente desde la app del usuario
(change: firma-cliente-diferida-checklist).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0007_adjudicacion_pendiente_creditos'),
    ]

    operations = [
        migrations.AlterField(
            model_name='solicitudservicio',
            name='estado',
            field=models.CharField(
                choices=[
                    ('pendiente', 'Pendiente'),
                    ('pago_validado', 'Pago Validado'),
                    ('confirmado', 'Confirmado'),
                    ('pendiente_aceptacion_proveedor', 'Pendiente de Aceptación del Proveedor'),
                    ('aceptada_por_proveedor', 'Aceptada por Proveedor'),
                    ('rechazada_por_proveedor', 'Rechazada por Proveedor'),
                    ('checklist_en_progreso', 'Checklist en Progreso'),
                    ('checklist_completado', 'Checklist Completado'),
                    ('en_proceso', 'En Proceso'),
                    ('pendiente_firma_cliente', 'Pendiente de Firma del Cliente'),
                    ('completado', 'Completado'),
                    ('cancelado', 'Cancelado'),
                    ('solicitud_cancelacion', 'Solicitud de Cancelación'),
                    ('pendiente_devolucion', 'Pendiente de Devolución'),
                    ('devuelto', 'Devuelto'),
                ],
                default='pendiente',
                max_length=40,
            ),
        ),
    ]
