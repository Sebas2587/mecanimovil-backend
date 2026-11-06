# Generated manually for taller profit margin feature

from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0026_taller_prefijo_folio'),
    ]

    operations = [
        migrations.AddField(
            model_name='taller',
            name='margen_ganancia_pct',
            field=models.DecimalField(
                blank=True,
                null=True,
                max_digits=5,
                decimal_places=2,
                validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('999.99'))],
                help_text='Margen de ganancia sobre costo de repuestos (%). Ejemplo: 30 significa vender a costo × 1.30',
                verbose_name='Margen de ganancia (%)',
            ),
        ),
    ]
