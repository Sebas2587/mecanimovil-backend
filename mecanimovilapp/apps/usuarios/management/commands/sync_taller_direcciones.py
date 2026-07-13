"""
Backfill: talleres con geo o usuario.direccion pero sin TallerDireccion.
Uso: python manage.py sync_taller_direcciones [--dry-run]
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from mecanimovilapp.apps.usuarios.models import Taller
from mecanimovilapp.apps.usuarios.taller_direccion_utils import upsert_taller_direccion_fisica


class Command(BaseCommand):
    help = 'Sincroniza TallerDireccion desde usuario.direccion (o reverse geocode si falta texto)'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--reverse-geocode', action='store_true',
                            help='Si no hay texto, intenta reverse geocode (Nominatim, lento)')

    def handle(self, *args, **options):
        dry = options['dry_run']
        do_rev = options['reverse_geocode']
        qs = Taller.objects.filter(activo=True).select_related('usuario', 'direccion_fisica')
        created = 0
        skipped = 0
        for taller in qs.iterator():
            has_df = False
            try:
                df = taller.direccion_fisica
                has_df = bool(df and (df.calle or df.comuna))
            except Exception:
                has_df = False
            if has_df:
                skipped += 1
                continue

            text = ''
            user = getattr(taller, 'usuario', None)
            if user and getattr(user, 'direccion', None):
                text = str(user.direccion).strip()

            if not text and do_rev and taller.ubicacion:
                try:
                    from mecanimovilapp.apps.usuarios.geocoding_utils import reverse_geocode_chile
                    rev = reverse_geocode_chile(taller.ubicacion.y, taller.ubicacion.x)
                    text = (rev or {}).get('display_name') or ''
                except Exception as e:
                    self.stderr.write(f'  reverse fail {taller.id}: {e}')

            if not text:
                skipped += 1
                continue

            self.stdout.write(f'{"[dry] " if dry else ""}Taller {taller.id} {taller.nombre}: {text[:80]}')
            if not dry:
                upsert_taller_direccion_fisica(taller, text)
                created += 1
            else:
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done. upserted={created} skipped={skipped} dry_run={dry}'
        ))
