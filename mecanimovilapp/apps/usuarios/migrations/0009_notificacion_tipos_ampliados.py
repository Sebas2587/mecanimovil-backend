from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0008_notificacion_soft_delete'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notificacion',
            name='tipo',
            field=models.CharField(
                choices=[
                    ('health_alert', 'Alerta de Salud'),
                    ('salud_actualizada', 'Salud Actualizada'),
                    ('viaje_registrado', 'Viaje Registrado'),
                    ('payment_reminder', 'Recordatorio de Pago'),
                    ('order_update', 'Actualización de Orden'),
                    ('nueva_oferta', 'Nueva Oferta'),
                    ('solicitud_adjudicada', 'Solicitud Adjudicada'),
                    ('system', 'Sistema'),
                ],
                help_text='Tipo de notificación',
                max_length=50,
            ),
        ),
    ]
