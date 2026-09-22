from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('omnichannel', '0002_ensure_providerchannelconnection_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='externalcontact',
            name='rol',
            field=models.CharField(
                choices=[
                    ('sin_clasificar', 'Sin clasificar'),
                    ('cliente_nuevo', 'Cliente nuevo'),
                    ('cliente_recurrente', 'Cliente recurrente'),
                    ('solo_consulta', 'Solo consulta'),
                    ('casa_repuestos', 'Casa de repuestos'),
                    ('otro', 'Otro'),
                ],
                db_index=True,
                default='sin_clasificar',
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name='externalcontact',
            name='rol_manual',
            field=models.BooleanField(
                default=False,
                help_text='Si el taller fijó el rol, el sistema no lo pisa.',
            ),
        ),
        migrations.AddField(
            model_name='externalcontact',
            name='rol_sugerido',
            field=models.CharField(blank=True, default='', max_length=24),
        ),
    ]
