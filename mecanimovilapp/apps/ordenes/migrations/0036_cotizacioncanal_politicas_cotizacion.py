from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0035_cotizacioncanal_folio_emisor'),
    ]

    operations = [
        migrations.AddField(
            model_name='cotizacioncanal',
            name='politicas_cotizacion',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Políticas de validez del taller (snapshot). Se muestran en el recuadro Validez.',
            ),
        ),
    ]
