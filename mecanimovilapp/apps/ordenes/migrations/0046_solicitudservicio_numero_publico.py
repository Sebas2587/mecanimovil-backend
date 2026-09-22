import re

from django.db import migrations, models

_FOLIO_N_RE = re.compile(r'^MM-(\d+)$', re.IGNORECASE)


def _folio(n: int) -> str:
    return f'MM-{int(n):06d}'


def backfill_folio_ordenes(apps, schema_editor):
    Orden = apps.get_model('ordenes', 'SolicitudServicio')
    Cotizacion = apps.get_model('ordenes', 'CotizacionCanal')
    Cita = apps.get_model('ordenes', 'CitaAgendaPersonal')

    ocupados = set()
    for model in (Cotizacion, Cita, Orden):
        qs = model.objects.exclude(numero_publico='')
        if model is Cotizacion:
            qs = qs.exclude(numero_publico__isnull=True)
        ocupados.update(str(f).strip() for f in qs.values_list('numero_publico', flat=True) if f)

    max_n = 0
    for folio in ocupados:
        m = _FOLIO_N_RE.match(folio)
        if m:
            max_n = max(max_n, int(m.group(1)))

    for orden in Orden.objects.iterator():
        if (orden.numero_publico or '').strip():
            ocupados.add(orden.numero_publico.strip())
            continue
        preferred = _folio(orden.pk)
        if preferred not in ocupados:
            folio = preferred
        else:
            max_n += 1
            folio = _folio(max_n)
            while folio in ocupados:
                max_n += 1
                folio = _folio(max_n)
        orden.numero_publico = folio
        orden.save(update_fields=['numero_publico'])
        ocupados.add(folio)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0045_citaagendapersonal_numero_publico'),
    ]

    operations = [
        migrations.AddField(
            model_name='solicitudservicio',
            name='numero_publico',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='Folio MM del caso. Mismo pool que cotizaciones y citas (MM-000184).',
                max_length=16,
            ),
        ),
        migrations.RunPython(backfill_folio_ordenes, noop_reverse),
    ]
