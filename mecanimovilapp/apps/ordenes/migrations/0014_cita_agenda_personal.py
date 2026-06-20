# Generated manually for agenda-citas-personales

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0008_ofertaservicio_tipo_motor'),
        ('usuarios', '0014_notificacion_review_reminder_tipo'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ordenes', '0013_patron_aprendizaje_necesidad'),
    ]

    operations = [
        migrations.CreateModel(
            name='CitaAgendaPersonal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha_servicio', models.DateField()),
                ('hora_servicio', models.TimeField()),
                ('duracion_minutos', models.PositiveIntegerField(default=60)),
                ('tipo_servicio', models.CharField(choices=[('taller', 'Taller'), ('domicilio', 'Domicilio')], max_length=20)),
                ('estado', models.CharField(choices=[('activa', 'Activa'), ('cerrada', 'Cerrada'), ('cancelada', 'Cancelada')], db_index=True, default='activa', max_length=20)),
                ('cerrada_en', models.DateTimeField(blank=True, null=True)),
                ('cancelada_en', models.DateTimeField(blank=True, null=True)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
                ('creado_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='citas_agenda_personal_creadas', to=settings.AUTH_USER_MODEL)),
                ('mecanico', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='citas_agenda_personal', to='usuarios.mecanicodomicilio')),
                ('taller', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='citas_agenda_personal', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'cita agenda personal',
                'verbose_name_plural': 'citas agenda personal',
            },
        ),
        migrations.CreateModel(
            name='CitaAgendaPersonalDetalle',
            fields=[
                ('cita', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='detalle', serialize=False, to='ordenes.citaagendapersonal')),
                ('cliente_nombre', models.CharField(max_length=200)),
                ('cliente_telefono', models.CharField(blank=True, default='', max_length=20)),
                ('direccion', models.CharField(blank=True, default='', max_length=500)),
                ('vehiculo_marca', models.CharField(blank=True, default='', max_length=100)),
                ('vehiculo_modelo', models.CharField(blank=True, default='', max_length=100)),
                ('vehiculo_patente', models.CharField(blank=True, default='', max_length=20)),
                ('vehiculo_anio', models.PositiveIntegerField(blank=True, null=True)),
                ('vehiculo_cilindraje', models.CharField(blank=True, default='', max_length=30)),
                ('vehiculo_color', models.CharField(blank=True, default='', max_length=30)),
                ('servicio_nombre', models.CharField(blank=True, default='', max_length=255)),
                ('descripcion', models.TextField(blank=True, default='')),
                ('precio_referencia', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ('oferta_servicio', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='citas_agenda_personal', to='servicios.ofertaservicio')),
            ],
            options={
                'verbose_name': 'detalle cita agenda personal',
                'verbose_name_plural': 'detalles cita agenda personal',
            },
        ),
        migrations.AddConstraint(
            model_name='citaagendapersonal',
            constraint=models.CheckConstraint(check=models.Q(('taller__isnull', False), ('mecanico__isnull', True), _connector='OR') | models.Q(('taller__isnull', True), ('mecanico__isnull', False)), name='cita_xor_proveedor'),
        ),
        migrations.AddConstraint(
            model_name='citaagendapersonal',
            constraint=models.CheckConstraint(check=models.Q(('duracion_minutos__gt', 0)), name='cita_duracion_positiva'),
        ),
        migrations.AddConstraint(
            model_name='citaagendapersonal',
            constraint=models.CheckConstraint(check=models.Q(('estado', 'cerrada'), _negated=True) | models.Q(('cerrada_en__isnull', False)), name='cita_cerrada_requiere_ts'),
        ),
        migrations.AddConstraint(
            model_name='citaagendapersonal',
            constraint=models.CheckConstraint(check=models.Q(('estado', 'cancelada'), _negated=True) | models.Q(('cancelada_en__isnull', False)), name='cita_cancelada_requiere_ts'),
        ),
        migrations.AddConstraint(
            model_name='citaagendapersonaldetalle',
            constraint=models.CheckConstraint(check=models.Q(('oferta_servicio__isnull', False), ('servicio_nombre', ''), _negated=True), name='cita_detalle_servicio_requerido'),
        ),
        migrations.AddIndex(
            model_name='citaagendapersonal',
            index=models.Index(fields=['taller', 'fecha_servicio', 'estado'], name='cita_taller_fecha_estado_idx'),
        ),
        migrations.AddIndex(
            model_name='citaagendapersonal',
            index=models.Index(fields=['mecanico', 'fecha_servicio', 'estado'], name='cita_mecanico_fecha_estado_idx'),
        ),
        migrations.AddIndex(
            model_name='citaagendapersonal',
            index=models.Index(fields=['creado_por', '-fecha_creacion'], name='cita_creado_por_idx'),
        ),
    ]
