from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0008_notificacion_soft_delete'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "ALTER INDEX IF EXISTS usuarios_no_usuario_elimina_idx RENAME TO usuarios_no_usr_eliminada_idx;",
                "CREATE INDEX IF NOT EXISTS usuarios_no_usr_eliminada_idx ON usuarios_notificaciones (usuario_id, eliminada);",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS usuarios_no_usr_eliminada_idx;",
            ],
            state_operations=[
                migrations.RemoveIndex(
                    model_name='notificacion',
                    name='usuarios_no_usuario_elimina_idx',
                ),
                migrations.AddIndex(
                    model_name='notificacion',
                    index=models.Index(
                        fields=['usuario', 'eliminada'],
                        name='usuarios_no_usr_eliminada_idx',
                    ),
                ),
            ],
        ),
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
