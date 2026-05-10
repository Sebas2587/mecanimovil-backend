# Generated manually: unifica conversaciones duplicadas (misma solicitud) y normaliza type.

from collections import defaultdict

from django.db import migrations


def merge_duplicate_service_conversations(apps, schema_editor):
    Conversation = apps.get_model('chat', 'Conversation')
    Message = apps.get_model('chat', 'Message')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    for conv in Conversation.objects.all():
        if conv.type not in ('SERVICE', 'MARKETPLACE'):
            conv.type = 'SERVICE'
            conv.save(update_fields=['type'])

    ct = ContentType.objects.filter(
        app_label='ordenes',
        model='solicitudserviciopublica',
    ).first()
    if not ct:
        return

    groups = defaultdict(list)
    qs = Conversation.objects.filter(content_type=ct).exclude(
        object_id__isnull=True,
    ).exclude(object_id='')
    for c in qs:
        groups[(c.content_type_id, str(c.object_id))].append(c)

    for _key, clist in groups.items():
        if len(clist) <= 1:
            continue

        def sort_key(cv):
            mc = Message.objects.filter(conversation_id=cv.id).count()
            is_svc = 0 if cv.type == 'SERVICE' else 1
            return (is_svc, -mc, cv.id)

        clist.sort(key=sort_key)
        keeper = clist[0]
        for dup in clist[1:]:
            for uid in dup.participants.values_list('id', flat=True):
                keeper.participants.add(uid)
            Message.objects.filter(conversation_id=dup.id).update(conversation_id=keeper.id)
            dup.delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0003_message_attachment_alter_message_content'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(merge_duplicate_service_conversations, noop_reverse),
    ]
