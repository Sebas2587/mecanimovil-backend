import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0004_merge_duplicate_service_conversations'),
        ('omnichannel', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversation',
            name='external_thread_id',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='conversation',
            name='source_channel',
            field=models.CharField(
                choices=[
                    ('APP', 'App'),
                    ('WHATSAPP', 'WhatsApp'),
                    ('MESSENGER', 'Messenger'),
                    ('INSTAGRAM', 'Instagram'),
                ],
                db_index=True,
                default='APP',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='conversation',
            name='external_contact',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='conversations',
                to='omnichannel.externalcontact',
            ),
        ),
        migrations.AlterField(
            model_name='conversation',
            name='type',
            field=models.CharField(
                choices=[
                    ('SERVICE', 'Servicio'),
                    ('MARKETPLACE', 'Negocio'),
                    ('OMNICHANNEL', 'Omnicanal'),
                ],
                default='SERVICE',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='message',
            name='channel_metadata',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='message',
            name='direction',
            field=models.CharField(
                choices=[('inbound', 'Entrante'), ('outbound', 'Saliente')],
                default='outbound',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='message',
            name='external_message_id',
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='message',
            name='sender',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='sent_messages',
                to='usuarios.usuario',
            ),
        ),
    ]
