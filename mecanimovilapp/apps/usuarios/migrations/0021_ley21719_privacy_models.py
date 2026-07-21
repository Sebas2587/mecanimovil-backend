# Generated manually for Ley 21.719 compliance

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0020_webpushsubscription_app_origen'),
    ]

    operations = [
        migrations.AddField(
            model_name='usuario',
            name='anonymized_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='usuario',
            name='deleted_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.CreateModel(
            name='ConsentimientoUsuario',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(
                    choices=[
                        ('terminos', 'Términos de uso'),
                        ('privacidad', 'Política de privacidad'),
                        ('marketing', 'Comunicaciones comerciales'),
                    ],
                    db_index=True,
                    max_length=20,
                )),
                ('version_documento', models.CharField(max_length=32)),
                ('fecha_aceptacion', models.DateTimeField(auto_now_add=True)),
                ('canal', models.CharField(
                    choices=[
                        ('app_usuarios', 'App usuarios'),
                        ('app_prov', 'App proveedores'),
                        ('google', 'Google Sign-In'),
                        ('web', 'Web'),
                    ],
                    db_index=True,
                    max_length=20,
                )),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, default='', max_length=500)),
                ('usuario', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='consentimientos',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'consentimiento de usuario',
                'verbose_name_plural': 'consentimientos de usuario',
                'ordering': ['-fecha_aceptacion'],
            },
        ),
        migrations.CreateModel(
            name='PreferenciasNotificacion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('push_operativo', models.BooleanField(
                    default=True,
                    help_text='Alertas de órdenes, citas y mensajes operativos.',
                )),
                ('push_marketing', models.BooleanField(
                    default=False,
                    help_text='Promociones y novedades comerciales.',
                )),
                ('email_marketing', models.BooleanField(
                    default=False,
                    help_text='Correos comerciales.',
                )),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
                ('usuario', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='preferencias_notificacion',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'preferencias de notificación',
                'verbose_name_plural': 'preferencias de notificación',
            },
        ),
        migrations.AddIndex(
            model_name='consentimientousuario',
            index=models.Index(
                fields=['usuario', 'tipo', '-fecha_aceptacion'],
                name='usuarios_co_usuario_8a1f2d_idx',
            ),
        ),
    ]
