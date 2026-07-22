import django.core.validators
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('usuarios', '0022_consentimiento_ubicacion'),
        ('suscripciones', '0007_ensure_cobrosuscripcion_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='plansuscripcion',
            name='acceso_endpoints_patente_pro',
            field=models.BooleanField(default=False, verbose_name='Acceso endpoints patente PRO (VIN, robo, PRT)'),
        ),
        migrations.AddField(
            model_name='plansuscripcion',
            name='canales_mensajeria_max',
            field=models.IntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Canales de mensajería incluidos'),
        ),
        migrations.AddField(
            model_name='plansuscripcion',
            name='consultas_patente_mensuales',
            field=models.IntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Consultas de patente mensuales incluidas'),
        ),
        migrations.AddField(
            model_name='plansuscripcion',
            name='conversaciones_salientes_max',
            field=models.IntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Tope conversaciones salientes/mes'),
        ),
        migrations.AddField(
            model_name='plansuscripcion',
            name='cotizaciones_ia_mensuales',
            field=models.IntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Cotizaciones IA mensuales incluidas'),
        ),
        migrations.AddField(
            model_name='plansuscripcion',
            name='diagnosticos_ia_mensuales',
            field=models.IntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Diagnósticos IA mensuales incluidos'),
        ),
        migrations.AddField(
            model_name='plansuscripcion',
            name='overage_cotizaciones_por_credito',
            field=models.IntegerField(default=3, validators=[django.core.validators.MinValueValidator(1)], verbose_name='Cotizaciones extra por 1 crédito (overage)'),
        ),
        migrations.AddField(
            model_name='plansuscripcion',
            name='overage_diagnosticos_por_credito',
            field=models.IntegerField(default=4, validators=[django.core.validators.MinValueValidator(1)], verbose_name='Diagnósticos extra por 1 crédito (overage)'),
        ),
        migrations.AddField(
            model_name='plansuscripcion',
            name='overage_patentes_por_credito',
            field=models.IntegerField(default=3, validators=[django.core.validators.MinValueValidator(1)], verbose_name='Consultas patente extra por 1 crédito (overage)'),
        ),
        migrations.CreateModel(
            name='ConsumoFeatureMensual',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('feature', models.CharField(choices=[('COTIZACION_IA', 'Cotización IA'), ('DIAGNOSTICO_IA', 'Diagnóstico IA'), ('CONSULTA_PATENTE', 'Consulta patente'), ('CONVERSACION_SALIENTE', 'Conversación saliente')], max_length=40)),
                ('periodo', models.CharField(help_text='Mes calendario del consumo', max_length=7, verbose_name='Periodo (YYYY-MM)')),
                ('usados', models.IntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Usos del mes')),
                ('creditos_overage_gastados', models.IntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Créditos gastados en overage')),
                ('unidades_overage_pendientes', models.IntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Unidades acumuladas hacia próximo crédito overage')),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
                ('proveedor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='consumos_feature_mensual', to=settings.AUTH_USER_MODEL, verbose_name='Proveedor (dueño suscripción)')),
                ('taller', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='consumos_feature_mensual', to='usuarios.taller', verbose_name='Taller')),
            ],
            options={
                'verbose_name': 'Consumo feature mensual',
                'verbose_name_plural': 'Consumos feature mensual',
            },
        ),
        migrations.AddConstraint(
            model_name='consumofeaturemensual',
            constraint=models.UniqueConstraint(fields=('proveedor', 'feature', 'periodo'), name='uniq_consumo_feature_mensual_proveedor'),
        ),
        migrations.AddIndex(
            model_name='consumofeaturemensual',
            index=models.Index(fields=['proveedor', 'periodo'], name='suscripcion_proveed_6a1b2c_idx'),
        ),
        migrations.AddIndex(
            model_name='consumofeaturemensual',
            index=models.Index(fields=['taller', 'periodo'], name='suscripcion_taller__7d3e4f_idx'),
        ),
    ]
