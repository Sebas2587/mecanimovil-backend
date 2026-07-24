from django.core.management.base import BaseCommand
from django.db.models import Q

from mecanimovilapp.apps.chat.models import Message
from mecanimovilapp.apps.omnichannel.tasks import fetch_inbound_meta_media


class Command(BaseCommand):
    help = (
        'Reencola la descarga de adjuntos de mensajes inbound (WhatsApp/Messenger/Instagram) '
        'que quedaron con media_error (ej. por el bug de 401 del CDN de Meta ya corregido).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Solo mostrar cuántos mensajes se reencolarían, sin encolar nada.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Máximo de mensajes a reencolar (por defecto todos).',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']

        qs = Message.objects.filter(
            Q(attachment='') | Q(attachment__isnull=True),
            channel_metadata__has_key='media_error',
        ).order_by('-id')
        if limit:
            qs = qs[:limit]

        ids = list(qs.values_list('id', flat=True))
        self.stdout.write(f'{len(ids)} mensajes con media_error pendiente de reintento.')

        if dry_run:
            self.stdout.write(self.style.WARNING('MODO DRY-RUN: no se encoló nada.'))
            return

        for message_id in ids:
            fetch_inbound_meta_media.delay(message_id)

        self.stdout.write(self.style.SUCCESS(f'Reencolados {len(ids)} mensajes.'))
