from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0030_cotizacion_adicional'),
    ]

    operations = [
        migrations.AddField(
            model_name='cotizacioncanal',
            name='notas_internas',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Comentarios internos del taller; no se exponen al cliente.',
            ),
        ),
    ]
