from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0026_taller_prefijo_folio'),
        ('ordenes', '0048_cobro_anotado_caso'),
    ]

    operations = [
        migrations.CreateModel(
            name='VistaTallerOculta',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(choices=[('cotizacion', 'Cotización'), ('cita', 'Cita'), ('orden', 'Orden'), ('oferta', 'Oferta')], max_length=16)),
                ('objeto_id', models.CharField(max_length=64)),
                ('oculto_en', models.DateTimeField(auto_now_add=True)),
                ('taller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='vista_oculta', to='usuarios.taller')),
            ],
        ),
        migrations.AddConstraint(
            model_name='vistatalleroculta',
            constraint=models.UniqueConstraint(fields=('taller', 'tipo', 'objeto_id'), name='vista_taller_oculta_uniq'),
        ),
        migrations.AddIndex(
            model_name='vistatalleroculta',
            index=models.Index(fields=['taller', 'tipo'], name='vista_taller_oculta_tipo_idx'),
        ),
    ]
