# Generated manually for Ley 21.719 — TTL cotización pública

from django.utils import timezone
from datetime import timedelta

from django.db import migrations, models


def set_expiracion_cotizaciones_enviadas(apps, schema_editor):
    CotizacionCanal = apps.get_model('ordenes', 'CotizacionCanal')
    limite = timezone.now() + timedelta(days=30)
    CotizacionCanal.objects.filter(
        es_libre=True,
        token__isnull=False,
        fecha_expiracion_publica__isnull=True,
    ).update(fecha_expiracion_publica=limite)


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0028_cotizacioncanal_direccion_servicio'),
    ]

    operations = [
        migrations.AddField(
            model_name='cotizacioncanal',
            name='fecha_expiracion_publica',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(set_expiracion_cotizaciones_enviadas, migrations.RunPython.noop),
    ]
