# Generated manually for Ley 21.719 — TTL informe público

from django.utils import timezone
from datetime import timedelta

from django.db import migrations, models


def set_fecha_expiracion_existentes(apps, schema_editor):
    InformeServicioPublico = apps.get_model('checklists', 'InformeServicioPublico')
    limite = timezone.now() + timedelta(days=30)
    InformeServicioPublico.objects.filter(fecha_expiracion__isnull=True).update(
        fecha_expiracion=limite,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0008_informe_publico_firma_supervisor'),
    ]

    operations = [
        migrations.AddField(
            model_name='informeserviciopublico',
            name='fecha_expiracion',
            field=models.DateTimeField(
                db_index=True,
                help_text='Vencimiento del enlace público del informe.',
                null=True,
            ),
        ),
        migrations.RunPython(set_fecha_expiracion_existentes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='informeserviciopublico',
            name='fecha_expiracion',
            field=models.DateTimeField(
                db_index=True,
                help_text='Vencimiento del enlace público del informe.',
            ),
        ),
    ]
