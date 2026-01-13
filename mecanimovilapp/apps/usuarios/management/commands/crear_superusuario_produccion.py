"""
Comando de management para crear superusuario desde variables de entorno
Útil para producción cuando no se puede usar createsuperuser interactivamente
"""
import os
from django.core.management.base import BaseCommand
from mecanimovilapp.apps.usuarios.models import Usuario


class Command(BaseCommand):
    help = 'Crea un superusuario desde variables de entorno (ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            default=None,
            help='Username del superusuario (o usa ADMIN_USERNAME env var)'
        )
        parser.add_argument(
            '--email',
            type=str,
            default=None,
            help='Email del superusuario (o usa ADMIN_EMAIL env var)'
        )
        parser.add_argument(
            '--password',
            type=str,
            default=None,
            help='Password del superusuario (o usa ADMIN_PASSWORD env var)'
        )

    def handle(self, *args, **options):
        # Obtener valores de argumentos o variables de entorno
        username = options['username'] or os.environ.get('ADMIN_USERNAME', 'admin')
        email = options['email'] or os.environ.get('ADMIN_EMAIL', 'admin@mecanimovil.com')
        password = options['password'] or os.environ.get('ADMIN_PASSWORD')

        # Validar que tengamos password
        if not password:
            self.stdout.write(
                self.style.ERROR('❌ Error: ADMIN_PASSWORD no está configurada')
            )
            self.stdout.write(
                self.style.WARNING('   Configura ADMIN_PASSWORD en variables de entorno o usa --password')
            )
            return

        # Verificar si el usuario ya existe
        if Usuario.objects.filter(username=username).exists():
            user = Usuario.objects.get(username=username)
            if user.is_superuser:
                self.stdout.write(
                    self.style.WARNING(f'⚠️  El superusuario "{username}" ya existe')
                )
                self.stdout.write(
                    self.style.SUCCESS('   Si quieres cambiar la contraseña, usa: python manage.py changepassword')
                )
            else:
                # Convertir usuario existente a superusuario
                user.is_superuser = True
                user.is_staff = True
                user.set_password(password)
                if email:
                    user.email = email
                user.save()
                self.stdout.write(
                    self.style.SUCCESS(f'✅ Usuario "{username}" convertido a superusuario exitosamente')
                )
            return

        # Crear nuevo superusuario
        try:
            Usuario.objects.create_superuser(
                username=username,
                email=email,
                password=password
            )
            self.stdout.write(
                self.style.SUCCESS(f'✅ Superusuario "{username}" creado exitosamente')
            )
            self.stdout.write(f'   Username: {username}')
            self.stdout.write(f'   Email: {email}')
            self.stdout.write(
                self.style.WARNING('   ⚠️  Guarda estas credenciales de forma segura')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error al crear superusuario: {str(e)}')
            )
