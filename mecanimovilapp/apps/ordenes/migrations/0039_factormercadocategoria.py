from decimal import Decimal

from django.db import migrations, models


FACTORES_INICIALES = (
    ('bujias', Decimal('2.00')),
    ('frenos', Decimal('1.60')),
    ('filtros', Decimal('1.50')),
    ('aceites', Decimal('1.35')),
    ('suspension', Decimal('1.55')),
    ('embrague', Decimal('1.40')),
    ('distribucion', Decimal('1.45')),
    ('bateria', Decimal('1.30')),
    ('electrico', Decimal('1.70')),
    ('refrigeracion', Decimal('1.50')),
    ('otros', Decimal('1.50')),
)


def seed_factores(apps, schema_editor):
    FactorMercadoCategoria = apps.get_model('ordenes', 'FactorMercadoCategoria')
    for categoria, factor in FACTORES_INICIALES:
        FactorMercadoCategoria.objects.update_or_create(
            categoria=categoria,
            defaults={'factor': factor},
        )


def unseed_factores(apps, schema_editor):
    FactorMercadoCategoria = apps.get_model('ordenes', 'FactorMercadoCategoria')
    FactorMercadoCategoria.objects.filter(
        categoria__in=[c for c, _ in FACTORES_INICIALES],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0038_cotizacioncanal_dias_validez'),
    ]

    operations = [
        migrations.CreateModel(
            name='FactorMercadoCategoria',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('categoria', models.CharField(max_length=40, unique=True)),
                ('factor', models.DecimalField(decimal_places=2, default=Decimal('1.50'), max_digits=4)),
                ('muestras', models.PositiveIntegerField(default=0)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'factor mercado categoría',
                'verbose_name_plural': 'factores mercado categoría',
            },
        ),
        migrations.RunPython(seed_factores, unseed_factores),
    ]
