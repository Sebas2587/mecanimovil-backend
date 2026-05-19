# Patrones semánticos aprendidos de solicitudes confirmadas

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0002_initial'),
        ('vehiculos', '0024_vehiculo_descripcion_venta_fotovehiculomarketplace'),
        ('ordenes', '0012_ofertaproveedor_estado_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='PatronAprendizajeNecesidad',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fragmento', models.CharField(db_index=True, help_text='Palabras clave normalizadas (sin PII), ej: "ruido frenar pedal"', max_length=120)),
                ('componente_slug', models.CharField(blank=True, default='', max_length=64)),
                ('confirmaciones', models.PositiveIntegerField(default=1)),
                ('ultima_vez', models.DateTimeField(auto_now=True)),
                ('modelo', models.ForeignKey(blank=True, help_text='Opcional: patrón específico del modelo', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='patrones_necesidad', to='vehiculos.modelo')),
                ('servicio', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='patrones_aprendizaje', to='servicios.servicio')),
            ],
            options={
                'verbose_name': 'Patrón aprendizaje necesidad',
                'verbose_name_plural': 'Patrones aprendizaje necesidad',
            },
        ),
        migrations.AddIndex(
            model_name='patronaprendizajenecesidad',
            index=models.Index(fields=['fragmento'], name='ordenes_pat_fragmen_idx'),
        ),
        migrations.AddIndex(
            model_name='patronaprendizajenecesidad',
            index=models.Index(fields=['-confirmaciones', '-ultima_vez'], name='ordenes_pat_confirm_idx'),
        ),
        migrations.AddConstraint(
            model_name='patronaprendizajenecesidad',
            constraint=models.UniqueConstraint(fields=('fragmento', 'servicio', 'componente_slug', 'modelo'), name='uniq_patron_aprendizaje_necesidad'),
        ),
    ]
