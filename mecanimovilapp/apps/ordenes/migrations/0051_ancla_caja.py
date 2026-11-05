# Fila estable para serializar el caso aunque el libro esté vacío.

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0026_taller_prefijo_folio'),
        ('ordenes', '0050_cobro_taller'),
    ]

    operations = [
        migrations.CreateModel(
            name='AnclaCaja',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('ancla_tipo', models.CharField(choices=[('cita', 'Cita'), ('solicitud', 'Solicitud'), ('oferta', 'Oferta')], max_length=16)),
                ('ancla_id', models.CharField(max_length=64)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('taller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='anclas_caja', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'ancla de caja',
                'verbose_name_plural': 'anclas de caja',
            },
        ),
        migrations.AddConstraint(
            model_name='anclacaja',
            constraint=models.UniqueConstraint(fields=('taller', 'ancla_tipo', 'ancla_id'), name='ancla_caja_uniq'),
        ),
    ]
