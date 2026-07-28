from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agente_ia', '0010_talleragenteconfig_reglas_comerciales'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tallerconocimientochunk',
            name='fuente',
            field=models.CharField(
                choices=[
                    ('DOCUMENTO_TALLER', 'Documento del taller'),
                    ('CATALOGO_SERVICIO', 'Catálogo de servicios'),
                    ('HISTORICO_SERVICIO', 'Histórico de servicios'),
                    ('INSTRUCCION', 'Instrucciones personalizadas'),
                    ('CONVERSACION_EXITOSA', 'Conversación exitosa'),
                    ('LECCION_DIARIA', 'Lección diaria'),
                ],
                db_index=True,
                max_length=30,
            ),
        ),
        migrations.CreateModel(
            name='AgenteAprendizajeDiario',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField(db_index=True)),
                (
                    'tipo_hallazgo',
                    models.CharField(
                        choices=[
                            ('lead_perdido', 'Lead perdido'),
                            ('respuesta_insuficiente', 'Respuesta insuficiente'),
                            ('correccion_sistematica', 'Corrección sistemática'),
                            ('patron_alta_confianza', 'Patrón alta confianza'),
                        ],
                        db_index=True,
                        max_length=40,
                    ),
                ),
                ('detalle_json', models.JSONField(blank=True, default=dict)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                (
                    'taller',
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name='aprendizajes_diarios',
                        to='usuarios.taller',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Aprendizaje diario agente IA',
                'verbose_name_plural': 'Aprendizajes diarios agente IA',
                'indexes': [
                    models.Index(fields=['taller', '-fecha'], name='agente_ia_aprend_taller_fecha'),
                ],
            },
        ),
    ]
