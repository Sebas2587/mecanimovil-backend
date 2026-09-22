import re

from django.db import migrations, models

_FOLIO_N_RE = re.compile(r'^MM-(\d+)$', re.IGNORECASE)


def _folio(n: int) -> str:
    return f'MM-{int(n):06d}'


def backfill_folio_citas(apps, schema_editor):
    Cita = apps.get_model('ordenes', 'CitaAgendaPersonal')
    Cotizacion = apps.get_model('ordenes', 'CotizacionCanal')

    ocupados = {
        str(f).strip()
        for f in Cotizacion.objects.exclude(numero_publico__isnull=True)
        .exclude(numero_publico='')
        .values_list('numero_publico', flat=True)
        if f
    }
    max_n = 0
    for folio in ocupados:
        m = _FOLIO_N_RE.match(folio)
        if m:
            max_n = max(max_n, int(m.group(1)))

    for cita in Cita.objects.select_related('cotizacion_canal_origen').iterator():
        cot = getattr(cita, 'cotizacion_canal_origen', None)
        if cot is not None and (getattr(cot, 'numero_publico', None) or '').strip():
            folio = cot.numero_publico.strip()
            if cita.numero_publico != folio:
                cita.numero_publico = folio
                cita.save(update_fields=['numero_publico'])
            ocupados.add(folio)
            continue
        if (cita.numero_publico or '').strip():
            ocupados.add(cita.numero_publico.strip())
            continue
        max_n += 1
        folio = _folio(max_n)
        while folio in ocupados:
            max_n += 1
            folio = _folio(max_n)
        cita.numero_publico = folio
        cita.save(update_fields=['numero_publico'])
        ocupados.add(folio)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0044_vitrina_seleccion_repuesto'),
    ]

    operations = [
        migrations.AddField(
            model_name='citaagendapersonal',
            name='numero_publico',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='Folio MM del caso. Igual al de la cotización origen, o uno nuevo si nació en agenda.',
                max_length=16,
            ),
        ),
        migrations.RunPython(backfill_folio_citas, noop_reverse),
    ]
