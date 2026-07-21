# Generated manually for Ley 21.719 — ficha pública opt-in

import secrets

from django.db import migrations, models


def habilitar_ficha_existentes(apps, schema_editor):
    Vehiculo = apps.get_model('vehiculos', 'Vehiculo')
    for vehiculo in Vehiculo.objects.all().iterator():
        update_fields = ['ficha_publica_habilitada']
        vehiculo.ficha_publica_habilitada = True
        if not vehiculo.ficha_publica_token:
            vehiculo.ficha_publica_token = secrets.token_urlsafe(24)
            update_fields.append('ficha_publica_token')
        vehiculo.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ('vehiculos', '0032_forzar_snapshot_salud_claims'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehiculo',
            name='ficha_publica_habilitada',
            field=models.BooleanField(default=False, verbose_name='ficha pública habilitada'),
        ),
        migrations.AddField(
            model_name='vehiculo',
            name='ficha_publica_token',
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True, unique=True),
        ),
        migrations.RunPython(habilitar_ficha_existentes, migrations.RunPython.noop),
    ]
