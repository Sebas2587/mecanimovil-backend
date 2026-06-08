from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0012_proveedor_tipo_cobertura_marca'),
    ]

    operations = [
        migrations.CreateModel(
            name='WebPushSubscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('endpoint', models.TextField(help_text='URL de entrega del proveedor (Chrome/Firefox/etc.)', unique=True)),
                ('p256dh', models.TextField(help_text='Clave publica del cliente (base64url)')),
                ('auth', models.TextField(help_text='Secreto de autenticacion del cliente (base64url)')),
                ('user_agent', models.CharField(blank=True, default='', help_text='User-Agent del navegador al suscribirse', max_length=512)),
                ('activo', models.BooleanField(default=True, help_text='Suscripcion activa. Se desactiva cuando el endpoint devuelve 410 Gone.')),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
                ('usuario', models.ForeignKey(
                    help_text='Usuario propietario de la suscripcion',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='web_push_subscriptions',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Web Push Subscription',
                'verbose_name_plural': 'Web Push Subscriptions',
                'db_table': 'usuarios_web_push_subscriptions',
                'ordering': ['-fecha_creacion'],
                'indexes': [
                    models.Index(fields=['usuario', 'activo'], name='usuarios_we_usuario_activo_idx'),
                ],
            },
        ),
    ]
