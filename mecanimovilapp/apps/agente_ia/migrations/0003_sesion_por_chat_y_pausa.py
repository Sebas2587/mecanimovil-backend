from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agente_ia', '0002_hnsw_embedding_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='agenteconversacionsesion',
            name='habilitado_en_chat',
            field=models.BooleanField(
                default=False,
                help_text='Si True, el agente responde en ESTA conversación. Independiente de otros chats.',
            ),
        ),
        migrations.AddField(
            model_name='agenteconversacionsesion',
            name='pausado_hasta',
            field=models.DateTimeField(
                blank=True,
                help_text='Si el taller intervino, la IA se reanuda automáticamente después de esta fecha.',
                null=True,
            ),
        ),
    ]
