# Generated manually for informe público + firma supervisor

import secrets

from django.db import migrations, models
import django.db.models.deletion


def _generar_token_informe():
    return secrets.token_urlsafe(24)


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0020_webpushsubscription_app_origen'),
        ('vehiculos', '0022_rename_evt_salud_comp_tipo_idx_vehiculos_e_compone_d77ded_idx_and_more'),
        ('checklists', '0007_checklist_cita_personal_ia_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='checklistinstance',
            name='estado',
            field=models.CharField(
                choices=[
                    ('PENDIENTE', 'Pendiente de inicio'),
                    ('EN_PROGRESO', 'En progreso'),
                    ('PAUSADO', 'Pausado temporalmente'),
                    ('PENDIENTE_FIRMA_SUPERVISOR', 'Pendiente de firma del supervisor'),
                    ('PENDIENTE_FIRMA_CLIENTE', 'Pendiente de firma del cliente'),
                    ('COMPLETADO', 'Completado'),
                    ('CANCELADO', 'Cancelado'),
                ],
                default='PENDIENTE',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='checklistinstance',
            name='fecha_firma_supervisor',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='checklistinstance',
            name='firma_supervisor',
            field=models.TextField(
                blank=True,
                help_text='Firma digital del supervisor/taller que rectifica el trabajo',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='checklistinstance',
            name='firma_supervisor_por',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='checklists_firmados_supervisor',
                to='usuarios.miembrotaller',
            ),
        ),
        migrations.CreateModel(
            name='InformeServicioPublico',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(db_index=True, default=_generar_token_informe, max_length=64, unique=True)),
                ('resumen_ia', models.TextField(blank=True, default='')),
                ('generado_en', models.DateTimeField(auto_now_add=True)),
                ('vehiculo_patente', models.CharField(blank=True, default='', max_length=20)),
                ('vehiculo_marca', models.CharField(blank=True, default='', max_length=100)),
                ('vehiculo_modelo', models.CharField(blank=True, default='', max_length=100)),
                ('vehiculo_anio', models.PositiveIntegerField(blank=True, null=True)),
                ('vehiculo_vin', models.CharField(blank=True, default='', max_length=30)),
                ('kilometraje_servicio', models.PositiveIntegerField(blank=True, null=True)),
                ('kilometraje_api', models.IntegerField(blank=True, null=True)),
                ('datos_patente_json', models.JSONField(blank=True, default=dict)),
                ('estado', models.CharField(
                    choices=[
                        ('PENDIENTE_FIRMA_CLIENTE', 'Pendiente de firma del cliente'),
                        ('FIRMADO', 'Firmado por el cliente'),
                        ('VEHICULO_RECLAMADO', 'Vehículo reclamado en la app'),
                    ],
                    default='PENDIENTE_FIRMA_CLIENTE',
                    max_length=30,
                )),
                ('firma_cliente', models.TextField(blank=True, null=True)),
                ('firmado_por_nombre', models.CharField(blank=True, default='', max_length=200)),
                ('fecha_firma_cliente', models.DateTimeField(blank=True, null=True)),
                ('reclamado_en', models.DateTimeField(blank=True, null=True)),
                ('enviado_via', models.CharField(
                    blank=True,
                    choices=[
                        ('whatsapp', 'WhatsApp'),
                        ('instagram', 'Instagram'),
                        ('messenger', 'Messenger'),
                        ('manual_link', 'Enlace manual'),
                    ],
                    default='',
                    max_length=20,
                )),
                ('url_publica', models.URLField(blank=True, default='', max_length=500)),
                ('checklist_instance', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='informe_publico',
                    to='checklists.checklistinstance',
                )),
                ('reclamado_por_cliente', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='informes_reclamados',
                    to='usuarios.cliente',
                )),
                ('reclamado_por_vehiculo', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='informes_reclamados',
                    to='vehiculos.vehiculo',
                )),
            ],
            options={
                'verbose_name': 'Informe público de servicio',
                'verbose_name_plural': 'Informes públicos de servicio',
                'ordering': ['-generado_en'],
            },
        ),
    ]
