from django.db import migrations, models


def backfill_numero_publico(apps, schema_editor):
    CotizacionCanal = apps.get_model('ordenes', 'CotizacionCanal')
    for cot in CotizacionCanal.objects.all().only('id', 'numero_publico').iterator():
        if cot.numero_publico:
            continue
        cot.numero_publico = f'MM-{cot.pk:06d}'
        cot.save(update_fields=['numero_publico'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0034_cotizacioncanal_ejecucion_adicional'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cotizacioncanal',
            name='notas_internas',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Notas de cotización (agente/taller). Editables; se exponen al cliente como notas_cotizacion.',
            ),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='numero_publico',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Folio humano inmutable, formato MM-000184.',
                max_length=16,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name='cotizacioncanal',
            name='emisor_snapshot',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Identidad del taller congelada al enviar (nombre, contacto, logo).',
            ),
        ),
        migrations.RunPython(backfill_numero_publico, noop_reverse),
    ]
