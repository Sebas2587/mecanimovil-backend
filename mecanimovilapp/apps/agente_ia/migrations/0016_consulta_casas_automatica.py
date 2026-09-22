from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agente_ia', '0015_alter_leadcalificacion_categoria_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='talleragenteconfig',
            name='consulta_casas_automatica',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'Si está activo, una línea sin precio consulta por WhatsApp a las casas '
                    'de repuestos del taller. Apagado, solo sale si el taller lo pide.'
                ),
            ),
        ),
    ]
