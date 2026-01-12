"""
Comando de management para agregar créditos a un usuario proveedor.
Ejecutar: python manage.py agregar_creditos --username james_rodriguez --cantidad 10
"""
from django.core.management.base import BaseCommand
from django.core.exceptions import ObjectDoesNotExist
from mecanimovilapp.apps.usuarios.models import Usuario
from mecanimovilapp.apps.suscripciones.creditos_services import obtener_credito_proveedor


class Command(BaseCommand):
    help = 'Agrega créditos a un usuario proveedor'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            required=True,
            help='Username del usuario proveedor'
        )
        parser.add_argument(
            '--cantidad',
            type=int,
            required=True,
            help='Cantidad de créditos a agregar'
        )

    def handle(self, *args, **options):
        username = options['username']
        cantidad = options['cantidad']
        
        self.stdout.write(f'Buscando usuario: {username}...')
        
        user = None
        
        # Intentar buscar por username exacto (case-insensitive)
        try:
            user = Usuario.objects.get(username__iexact=username)
        except Usuario.DoesNotExist:
            pass
        
        # Si no se encuentra, intentar buscar por email
        if not user:
            try:
                user = Usuario.objects.get(email__iexact=username)
            except Usuario.DoesNotExist:
                pass
        
        # Si no se encuentra, intentar búsqueda parcial en username o nombre
        if not user:
            usuarios_posibles = Usuario.objects.filter(
                username__icontains=username
            ) | Usuario.objects.filter(
                first_name__icontains=username
            ) | Usuario.objects.filter(
                last_name__icontains=username
            )
            
            if usuarios_posibles.count() == 1:
                user = usuarios_posibles.first()
            elif usuarios_posibles.count() > 1:
                self.stdout.write(self.style.WARNING(
                    f'\n⚠️  Se encontraron {usuarios_posibles.count()} usuarios que coinciden con "{username}":'
                ))
                for u in usuarios_posibles[:10]:
                    self.stdout.write(f'  - {u.username} (ID: {u.id}) - {u.first_name} {u.last_name} - {u.email}')
                return
        
        if not user:
            self.stdout.write(self.style.ERROR(
                f'❌ Error: No se encontró un usuario con "{username}"'
            ))
            self.stdout.write('\nBuscando usuarios que contengan "james" o "rodriguez"...')
            usuarios_james = Usuario.objects.filter(
                username__icontains='james'
            ) | Usuario.objects.filter(
                first_name__icontains='james'
            ) | Usuario.objects.filter(
                last_name__icontains='rodriguez'
            ) | Usuario.objects.filter(
                last_name__icontains='rodrigues'
            )
            
            if usuarios_james.exists():
                self.stdout.write(f'\nUsuarios encontrados ({usuarios_james.count()}):')
                for u in usuarios_james[:10]:
                    self.stdout.write(f'  - {u.username} (ID: {u.id}) - {u.first_name} {u.last_name} - {u.email}')
            else:
                self.stdout.write('\nUsuarios disponibles (últimos 10):')
                usuarios = Usuario.objects.all()[:10]
                for u in usuarios:
                    self.stdout.write(f'  - {u.username} (ID: {u.id})')
            return
        
        # Usuario encontrado
        self.stdout.write(self.style.SUCCESS(f'✓ Usuario encontrado: {user.username} (ID: {user.id})'))
        if user.first_name or user.last_name:
            self.stdout.write(f'  Nombre: {user.first_name} {user.last_name}')
        if user.email:
            self.stdout.write(f'  Email: {user.email}')
        
        # Verificar que sea proveedor
        if not user.es_mecanico:
            self.stdout.write(self.style.WARNING(
                f'⚠️  Advertencia: El usuario {user.username} no es un proveedor (es_mecanico=False). '
                'Agregando créditos de todas formas...'
            ))
        
        # Obtener o crear registro de créditos
        credito_proveedor = obtener_credito_proveedor(user)
        saldo_anterior = credito_proveedor.saldo_creditos
        
        # Agregar créditos
        credito_proveedor.saldo_creditos += cantidad
        credito_proveedor.save(update_fields=['saldo_creditos', 'fecha_actualizacion'])
        
        self.stdout.write(self.style.SUCCESS(
            f'\n✓ Créditos agregados exitosamente!\n'
            f'  Usuario: {user.username}\n'
            f'  Saldo anterior: {saldo_anterior} créditos\n'
            f'  Créditos agregados: +{cantidad} créditos\n'
            f'  Nuevo saldo: {credito_proveedor.saldo_creditos} créditos'
        ))
