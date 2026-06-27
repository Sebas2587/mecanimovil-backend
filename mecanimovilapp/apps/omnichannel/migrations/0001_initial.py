import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('contenttypes', '0002_remove_content_type_name'),
        ('usuarios', '0019_miembrotaller_foto'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProviderChannelConnection',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('object_id', models.PositiveIntegerField()),
                ('channel', models.CharField(choices=[('WHATSAPP', 'WhatsApp'), ('MESSENGER', 'Messenger'), ('INSTAGRAM', 'Instagram')], max_length=20)),
                ('enabled', models.BooleanField(default=False)),
                ('status', models.CharField(choices=[('no_configurada', 'Sin configurar'), ('pendiente', 'Pendiente'), ('conectada', 'Conectada'), ('desconectada', 'Desconectada'), ('error', 'Error')], default='no_configurada', max_length=20)),
                ('access_token', models.CharField(blank=True, max_length=500, null=True)),
                ('phone_number_id', models.CharField(blank=True, max_length=100, null=True)),
                ('waba_id', models.CharField(blank=True, max_length=100, null=True)),
                ('page_id', models.CharField(blank=True, max_length=100, null=True)),
                ('instagram_account_id', models.CharField(blank=True, max_length=100, null=True)),
                ('meta_business_id', models.CharField(blank=True, max_length=100, null=True)),
                ('display_name', models.CharField(blank=True, max_length=255, null=True)),
                ('display_identifier', models.CharField(blank=True, max_length=255, null=True)),
                ('oauth_state', models.CharField(blank=True, max_length=128, null=True)),
                ('mensaje_estado', models.TextField(blank=True, null=True)),
                ('connected_at', models.DateTimeField(blank=True, null=True)),
                ('disconnected_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('content_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype')),
                ('usuario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='channel_connections', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Conexión de canal proveedor',
                'verbose_name_plural': 'Conexiones de canal proveedor',
            },
        ),
        migrations.CreateModel(
            name='ExternalContact',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('channel', models.CharField(choices=[('WHATSAPP', 'WhatsApp'), ('MESSENGER', 'Messenger'), ('INSTAGRAM', 'Instagram')], max_length=20)),
                ('external_id', models.CharField(db_index=True, max_length=255)),
                ('display_name', models.CharField(blank=True, default='', max_length=255)),
                ('phone', models.CharField(blank=True, max_length=30, null=True)),
                ('profile_picture_url', models.URLField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('cliente', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='external_contacts', to='usuarios.cliente')),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='contacts', to='omnichannel.providerchannelconnection')),
            ],
            options={
                'verbose_name': 'Contacto externo',
                'verbose_name_plural': 'Contactos externos',
            },
        ),
        migrations.AddIndex(
            model_name='providerchannelconnection',
            index=models.Index(fields=['phone_number_id'], name='omnichannel_phone_idx'),
        ),
        migrations.AddIndex(
            model_name='providerchannelconnection',
            index=models.Index(fields=['page_id'], name='omnichannel_page_idx'),
        ),
        migrations.AddIndex(
            model_name='providerchannelconnection',
            index=models.Index(fields=['instagram_account_id'], name='omnichannel_ig_idx'),
        ),
        migrations.AddConstraint(
            model_name='providerchannelconnection',
            constraint=models.UniqueConstraint(fields=('content_type', 'object_id', 'channel'), name='unique_provider_channel'),
        ),
        migrations.AddConstraint(
            model_name='externalcontact',
            constraint=models.UniqueConstraint(fields=('connection', 'external_id'), name='unique_external_contact_per_connection'),
        ),
    ]
