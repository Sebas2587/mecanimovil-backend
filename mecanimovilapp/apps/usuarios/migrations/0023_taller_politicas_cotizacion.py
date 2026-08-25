from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0022_consentimiento_ubicacion'),
    ]

    operations = [
        migrations.AddField(
            model_name='taller',
            name='politicas_cotizacion',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Políticas de validez y trabajo. Se copian a cada cotización al crearla.',
            ),
        ),
        migrations.AddField(
            model_name='mecanicodomicilio',
            name='politicas_cotizacion',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Políticas de validez y trabajo. Se copian a cada cotización al crearla.',
            ),
        ),
    ]
