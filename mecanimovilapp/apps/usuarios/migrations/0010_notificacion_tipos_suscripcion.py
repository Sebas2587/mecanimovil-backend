from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0009_notificacion_tipos_ampliados'),
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
                    ('suscripcion_por_vencer', 'Suscripción Por Vencer'),
                    ('suscripcion_vencida', 'Suscripción Vencida'),
                    ('suscripcion_pago_fallido', 'Pago de Suscripción Fallido'),
                    ('creditos_agotados', 'Créditos Agotados'),
                    ('system', 'Sistema'),
                ],
                help_text='Tipo de notificación',
                max_length=50,
            ),
        ),
    ]
