"""
Configura CORS en el bucket R2 para que la web (expo-image) pueda cargar medios firmados.

Uso:
  python manage.py configure_r2_cors
"""
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = 'Configura CORS GET/HEAD en el bucket R2 (necesario para imágenes en web)'

    def handle(self, *args, **options):
        try:
            import boto3
        except ImportError as exc:
            raise CommandError('boto3 no está instalado') from exc

        bucket = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None)
        endpoint = getattr(settings, 'AWS_S3_ENDPOINT_URL', None)
        key = getattr(settings, 'AWS_ACCESS_KEY_ID', None)
        secret = getattr(settings, 'AWS_SECRET_ACCESS_KEY', None)
        region = getattr(settings, 'AWS_S3_REGION_NAME', 'auto')

        if not all([bucket, endpoint, key, secret]):
            raise CommandError(
                'Faltan variables R2/S3 (AWS_STORAGE_BUCKET_NAME, AWS_S3_ENDPOINT_URL, '
                'AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY).'
            )

        client = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name=region,
        )

        cors = {
            'CORSRules': [
                {
                    'AllowedOrigins': ['*'],
                    'AllowedMethods': ['GET', 'HEAD'],
                    'AllowedHeaders': ['*'],
                    'ExposeHeaders': ['ETag', 'Content-Length', 'Content-Type'],
                    'MaxAgeSeconds': 86400,
                }
            ]
        }
        client.put_bucket_cors(Bucket=bucket, CORSConfiguration=cors)
        self.stdout.write(self.style.SUCCESS(f'CORS configurado en bucket {bucket}'))
