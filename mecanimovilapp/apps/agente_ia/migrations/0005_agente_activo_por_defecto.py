from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agente_ia', '0004_sesion_agendando'),
    ]

    operations = [
        migrations.AlterField(
            model_name='agenteconversacionsesion',
            name='habilitado_en_chat',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'Si True, el agente responde en ESTA conversación. '
                    'Por defecto activo en chats nuevos; el taller debe desactivarlo para intervenir.'
                ),
            ),
        ),
    ]
