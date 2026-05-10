"""
Migra archivos de media existentes desde cPanel (HTTP) hacia Cloudflare R2.

Recorre todos los modelos del proyecto que tengan FileField/ImageField, descarga
cada archivo desde su URL pública actual (cPanel) y lo sube al bucket de R2.
Después actualiza el campo del modelo para que apunte al mismo path relativo
(que ahora vivirá en R2).

Uso:
    # Dry-run (no sube nada, solo muestra qué haría):
    python manage.py migrar_media_a_r2 --dry-run

    # Migración real:
    python manage.py migrar_media_a_r2

    # Migrar solo un modelo específico:
    python manage.py migrar_media_a_r2 --model usuarios.Usuario

    # Reanudar desde un offset (si se cortó):
    python manage.py migrar_media_a_r2 --offset 100

Variables de entorno requeridas (cPanel para descargar las fotos viejas):
    CPANEL_MEDIA_URL  -- URL pública base de cPanel donde están las fotos viejas

Variables de entorno requeridas (R2 para subir):
    R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_ENDPOINT_URL
"""

import io
import logging
import time
from urllib.parse import urlparse

import requests
from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db.models import FileField, ImageField

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Migra archivos de cPanel a Cloudflare R2"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='No sube ni modifica nada, solo lista lo que haría',
        )
        parser.add_argument(
            '--model',
            type=str,
            default=None,
            help='Migrar solo un modelo específico (formato: app_label.ModelName)',
        )
        parser.add_argument(
            '--offset',
            type=int,
            default=0,
            help='Saltar los primeros N archivos (útil para reanudar)',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=30,
            help='Timeout en segundos para descargar cada archivo (default: 30)',
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            default=True,
            help='Saltar archivos que ya existen en R2 (default: True)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        only_model = options['model']
        offset = options['offset']
        timeout = options['timeout']
        skip_existing = options['skip_existing']

        # Validar configuración
        cpanel_url = getattr(settings, 'CPANEL_MEDIA_URL', '')

        if not cpanel_url:
            raise CommandError(
                "CPANEL_MEDIA_URL no está configurado. Necesitamos esta URL "
                "para descargar las fotos viejas desde cPanel."
            )

        # Detectar si el storage actual es S3/R2 (compatible con boto3)
        from django.core.files.storage import default_storage
        storage_backend = type(default_storage).__module__ + '.' + type(default_storage).__name__
        if 's3boto3' not in storage_backend.lower() and 's3' not in storage_backend.lower():
            raise CommandError(
                f"Storage actual: '{storage_backend}'. "
                f"Debe estar configurado como S3/R2 antes de migrar. "
                f"Configura R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, etc."
            )

        self.stdout.write(self.style.SUCCESS(f"📦 Storage destino: {storage_backend}"))
        self.stdout.write(self.style.SUCCESS(f"🌐 Bucket: {getattr(settings, 'AWS_STORAGE_BUCKET_NAME', '?')}"))
        self.stdout.write(self.style.SUCCESS(f"🔗 cPanel URL base: {cpanel_url}"))
        self.stdout.write(self.style.SUCCESS(f"🧪 Dry-run: {dry_run}"))
        self.stdout.write("")

        # Recopilar todos los modelos con FileField/ImageField
        models_with_files = self._collect_models_with_file_fields(only_model)

        if not models_with_files:
            self.stdout.write(self.style.WARNING("No se encontraron modelos con FileField/ImageField."))
            return

        # Contar total
        total_files = 0
        for model, fields in models_with_files:
            for field in fields:
                count = model.objects.exclude(**{f"{field.name}__isnull": True}).exclude(**{f"{field.name}": ''}).count()
                total_files += count

        self.stdout.write(self.style.SUCCESS(f"📊 Total estimado: {total_files} archivos en {len(models_with_files)} modelos"))
        self.stdout.write("")

        # Migrar
        stats = {
            'migrated': 0,
            'skipped': 0,
            'errors': 0,
            'skipped_existing': 0,
        }

        for model, fields in models_with_files:
            self._migrate_model(
                model=model,
                fields=fields,
                cpanel_url=cpanel_url.rstrip('/'),
                dry_run=dry_run,
                offset=offset,
                timeout=timeout,
                skip_existing=skip_existing,
                stats=stats,
            )

        # Resumen
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("📊 RESUMEN DE MIGRACIÓN"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS(f"✅ Migrados:           {stats['migrated']}"))
        self.stdout.write(self.style.WARNING(f"⏭️  Ya existían en R2: {stats['skipped_existing']}"))
        self.stdout.write(self.style.WARNING(f"⏭️  Sin URL/inválidos: {stats['skipped']}"))
        self.stdout.write(self.style.ERROR(f"❌ Errores:            {stats['errors']}"))

    def _collect_models_with_file_fields(self, only_model=None):
        """Devuelve [(model_class, [field, field, ...]), ...]"""
        result = []
        for model in apps.get_models():
            if only_model:
                model_label = f"{model._meta.app_label}.{model.__name__}"
                if model_label.lower() != only_model.lower():
                    continue

            file_fields = [
                f for f in model._meta.get_fields()
                if isinstance(f, (FileField, ImageField))
            ]
            if file_fields:
                result.append((model, file_fields))
        return result

    def _migrate_model(self, model, fields, cpanel_url, dry_run, offset, timeout, skip_existing, stats):
        model_label = f"{model._meta.app_label}.{model.__name__}"
        field_names = [f.name for f in fields]

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO(f"🔄 Migrando {model_label} (campos: {', '.join(field_names)})"))

        for field in fields:
            qs = model.objects.exclude(**{f"{field.name}__isnull": True}).exclude(**{f"{field.name}": ''})
            total = qs.count()
            if total == 0:
                continue

            self.stdout.write(f"   → Campo '{field.name}': {total} archivos")

            for idx, instance in enumerate(qs.iterator()):
                if idx < offset:
                    continue

                file_field_value = getattr(instance, field.name, None)
                if not file_field_value:
                    stats['skipped'] += 1
                    continue

                # El name del file (ej: 'perfiles/foto.jpg')
                file_name = file_field_value.name
                if not file_name:
                    stats['skipped'] += 1
                    continue

                # Construir URL de cPanel para descargar
                source_url = f"{cpanel_url}/{file_name.lstrip('/')}"

                try:
                    self._migrate_one(
                        instance=instance,
                        field=field,
                        file_name=file_name,
                        source_url=source_url,
                        dry_run=dry_run,
                        timeout=timeout,
                        skip_existing=skip_existing,
                        stats=stats,
                        idx=idx,
                        total=total,
                    )
                except Exception as e:
                    stats['errors'] += 1
                    self.stdout.write(self.style.ERROR(
                        f"      ❌ [{idx + 1}/{total}] {file_name}: {e}"
                    ))

    def _migrate_one(self, instance, field, file_name, source_url, dry_run, timeout, skip_existing, stats, idx, total):
        from django.core.files.storage import default_storage

        # Verificar si ya existe en R2
        if skip_existing and default_storage.exists(file_name):
            stats['skipped_existing'] += 1
            self.stdout.write(f"      ⏭️  [{idx + 1}/{total}] {file_name} (ya en R2)")
            return

        if dry_run:
            stats['migrated'] += 1
            self.stdout.write(f"      🧪 [{idx + 1}/{total}] {file_name} ← {source_url}")
            return

        # Descargar de cPanel
        response = requests.get(source_url, timeout=timeout, stream=True)
        if response.status_code == 404:
            stats['skipped'] += 1
            self.stdout.write(self.style.WARNING(
                f"      ⚠️  [{idx + 1}/{total}] {file_name}: no existe en cPanel (404)"
            ))
            return

        response.raise_for_status()
        content = response.content

        if not content:
            stats['skipped'] += 1
            self.stdout.write(self.style.WARNING(
                f"      ⚠️  [{idx + 1}/{total}] {file_name}: archivo vacío"
            ))
            return

        # Subir a R2 manteniendo el mismo path
        default_storage.save(file_name, ContentFile(content))

        stats['migrated'] += 1
        size_kb = len(content) / 1024
        self.stdout.write(self.style.SUCCESS(
            f"      ✅ [{idx + 1}/{total}] {file_name} ({size_kb:.1f} KB)"
        ))

        # Pequeña pausa para no saturar R2/cPanel
        time.sleep(0.05)
