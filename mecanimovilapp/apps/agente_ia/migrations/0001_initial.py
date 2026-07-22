# Generated manually for agente_ia app

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import pgvector.django


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('chat', '0005_omnichannel_fields'),
        ('ordenes', '0029_cotizacion_fecha_expiracion_publica'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('usuarios', '0022_consentimiento_ubicacion'),
    ]

    operations = [
        pgvector.django.VectorExtension(),
        migrations.CreateModel(
            name='TallerAgenteConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('habilitado', models.BooleanField(default=False)),
                ('instrucciones_personalizadas', models.TextField(blank=True, default='')),
                ('canales_habilitados', models.JSONField(blank=True, default=list, help_text='Lista de canales donde el agente puede responder (WHATSAPP, MESSENGER, INSTAGRAM, APP).')),
                ('mensaje_bienvenida', models.TextField(blank=True, default='')),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('taller', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='agente_config', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'Configuración agente IA',
                'verbose_name_plural': 'Configuraciones agente IA',
            },
        ),
        migrations.CreateModel(
            name='TallerConocimientoDocumento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('titulo', models.CharField(max_length=255)),
                ('archivo', models.FileField(blank=True, null=True, upload_to='agente_ia/conocimiento/%Y/%m/')),
                ('texto_pegado', models.TextField(blank=True, default='')),
                ('estado_procesamiento', models.CharField(choices=[('pendiente', 'Pendiente'), ('procesando', 'Procesando'), ('listo', 'Listo'), ('error', 'Error')], db_index=True, default='pendiente', max_length=20)),
                ('error_detalle', models.TextField(blank=True, default='')),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('creado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='conocimiento_documentos_creados', to=settings.AUTH_USER_MODEL)),
                ('taller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='conocimiento_documentos', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'Documento de conocimiento',
                'verbose_name_plural': 'Documentos de conocimiento',
                'ordering': ['-creado_en'],
            },
        ),
        migrations.CreateModel(
            name='AgenteConversacionSesion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('estado', models.CharField(choices=[('capturando', 'Capturando información'), ('listo_para_cotizar', 'Listo para cotizar'), ('esperando_revision_taller', 'Esperando revisión del taller'), ('pausado_por_taller', 'Pausado por taller'), ('cerrado', 'Cerrado')], db_index=True, default='capturando', max_length=30)),
                ('datos_capturados', models.JSONField(blank=True, default=dict)),
                ('pausado_por_taller', models.BooleanField(default=False)),
                ('ultima_interaccion_ia', models.DateTimeField(blank=True, null=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('conversation', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='agente_sesion', to='chat.conversation')),
                ('cotizacion_borrador', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='agente_sesiones', to='ordenes.cotizacioncanal')),
                ('taller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='agente_sesiones', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'Sesión agente IA',
                'verbose_name_plural': 'Sesiones agente IA',
            },
        ),
        migrations.CreateModel(
            name='AgenteMensajeLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mensaje_entrante', models.TextField(blank=True, default='')),
                ('chunks_usados', models.JSONField(blank=True, default=list)),
                ('respuesta_generada', models.TextField(blank=True, default='')),
                ('accion', models.CharField(choices=[('responder', 'Responder'), ('escalar', 'Escalar a humano'), ('cotizar', 'Generar cotización'), ('ignorar', 'Ignorar')], max_length=20)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('fecha', models.DateTimeField(auto_now_add=True)),
                ('sesion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='agente_ia.agenteconversacionsesion')),
            ],
            options={
                'verbose_name': 'Log agente IA',
                'verbose_name_plural': 'Logs agente IA',
                'ordering': ['-fecha'],
            },
        ),
        migrations.CreateModel(
            name='TallerConocimientoChunk',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fuente', models.CharField(choices=[('DOCUMENTO_TALLER', 'Documento del taller'), ('CATALOGO_SERVICIO', 'Catálogo de servicios'), ('HISTORICO_SERVICIO', 'Histórico de servicios'), ('INSTRUCCION', 'Instrucciones personalizadas')], db_index=True, max_length=30)),
                ('contenido', models.TextField()),
                ('embedding', pgvector.django.VectorField(blank=True, dimensions=768, null=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('referencia_externa', models.CharField(blank=True, db_index=True, default='', help_text='Clave estable para upsert (ej. oferta_servicio:123).', max_length=128)),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
                ('documento', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='chunks', to='agente_ia.tallerconocimientodocumento')),
                ('taller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='conocimiento_chunks', to='usuarios.taller')),
            ],
            options={
                'verbose_name': 'Chunk de conocimiento',
                'verbose_name_plural': 'Chunks de conocimiento',
            },
        ),
        migrations.AddIndex(
            model_name='tallerconocimientochunk',
            index=models.Index(fields=['taller', 'fuente'], name='agente_ia_chunk_taller_fuente'),
        ),
        migrations.AddConstraint(
            model_name='tallerconocimientochunk',
            constraint=models.UniqueConstraint(condition=models.Q(('referencia_externa', ''), _negated=True), fields=('taller', 'referencia_externa'), name='agente_ia_chunk_ref_unica'),
        ),
    ]
