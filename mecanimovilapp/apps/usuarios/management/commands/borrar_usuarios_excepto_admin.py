"""
Comando de management para borrar todos los usuarios excepto admin
y todos los elementos asociados en cascada.

IMPORTANTE: Este comando es destructivo y no se puede deshacer.
Solo usar en desarrollo o cuando se necesite limpiar completamente la base de datos.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
import logging

# Importar todos los modelos relacionados
from mecanimovilapp.apps.usuarios.models import (
    Usuario, Cliente, DireccionUsuario, Taller, MecanicoDomicilio, ProviderProfile
)
from mecanimovilapp.apps.vehiculos.models import Vehiculo
from mecanimovilapp.apps.ordenes.models import (
    SolicitudServicio, SolicitudServicioPublica, CarritoAgendamiento,
    OfertaServicio, AlertaDescartada, AuditAccesoCliente
)
from mecanimovilapp.apps.pagos.models import (
    Pago, PreferenciaPago, CuentaMercadoPagoProveedor
)
from mecanimovilapp.apps.suscripciones.models import (
    CreditoProveedor, CompraCreditos, ProveedorCancelaciones
)
from mecanimovilapp.apps.checklists.models import ChecklistInstance
from mecanimovilapp.apps.vehiculos.models_health import (
    EstadoSaludVehiculo, ComponenteSaludVehiculo, AlertaMantenimiento
)
from mecanimovilapp.apps.personalizacion.models import (
    RecomendacionPersonalizada, VehiculoActivo
)

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = 'Borra todos los usuarios excepto admin y todos los elementos asociados en cascada'

    def add_arguments(self, parser):
        parser.add_argument(
            '--admin-username',
            type=str,
            default='admin',
            help='Username del usuario admin a preservar (default: admin)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostrar qué se borraría sin hacer cambios reales'
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Confirmar el borrado (requerido para ejecutar)'
        )
        parser.add_argument(
            '--skip-related',
            action='store_true',
            help='Saltar el borrado de elementos relacionados (solo borrar usuarios)'
        )

    def handle(self, *args, **options):
        admin_username = options['admin_username']
        dry_run = options['dry_run']
        confirm = options['confirm']
        skip_related = options['skip_related']

        # Obtener usuario admin
        try:
            admin_user = User.objects.get(username=admin_username)
            self.stdout.write(
                self.style.SUCCESS(f'✅ Usuario admin encontrado: {admin_username} (ID: {admin_user.id})')
            )
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'❌ Error: Usuario admin "{admin_username}" no encontrado')
            )
            return

        # Obtener todos los usuarios excepto admin
        usuarios_a_borrar = User.objects.exclude(id=admin_user.id)
        total_usuarios = usuarios_a_borrar.count()

        if total_usuarios == 0:
            self.stdout.write(
                self.style.WARNING('⚠️ No hay usuarios para borrar (solo existe el admin)')
            )
            return

        # Mostrar resumen
        self.stdout.write('\n' + '='*80)
        self.stdout.write(self.style.WARNING('⚠️  ADVERTENCIA: OPERACIÓN DESTRUCTIVA'))
        self.stdout.write('='*80)
        self.stdout.write(f'\n📊 Resumen de borrado:')
        self.stdout.write(f'   - Usuarios a borrar: {total_usuarios}')
        self.stdout.write(f'   - Usuario preservado: {admin_username} (ID: {admin_user.id})')
        self.stdout.write(f'   - Modo dry-run: {"SÍ" if dry_run else "NO"}')
        self.stdout.write(f'   - Saltar relacionados: {"SÍ" if skip_related else "NO"}')

        if not skip_related:
            # Contar elementos relacionados
            self.stdout.write(f'\n📋 Elementos relacionados a borrar:')
            
            # Contar por usuario
            stats = {
                'clientes': 0,
                'talleres': 0,
                'mecanicos': 0,
                'vehiculos': 0,
                'solicitudes': 0,
                'pagos': 0,
                'suscripciones': 0,
                'checklists': 0,
            }
            
            for usuario in usuarios_a_borrar:
                if hasattr(usuario, 'cliente'):
                    stats['clientes'] += 1
                    cliente = usuario.cliente
                    stats['vehiculos'] += cliente.vehiculos.count()
                    stats['solicitudes'] += cliente.solicitudes.count()
                
                if hasattr(usuario, 'taller'):
                    stats['talleres'] += 1
                
                if hasattr(usuario, 'mecanico_domicilio'):
                    stats['mecanicos'] += 1
                
                stats['pagos'] += usuario.pagos.count()
                
                if hasattr(usuario, 'suscripcion'):
                    stats['suscripciones'] += 1
            
            stats['checklists'] = ChecklistInstance.objects.filter(
                orden__vehiculo__cliente__usuario__in=usuarios_a_borrar
            ).count()
            
            for key, value in stats.items():
                self.stdout.write(f'   - {key.capitalize()}: {value}')

        # Confirmación
        if not dry_run and not confirm:
            self.stdout.write('\n' + '='*80)
            self.stdout.write(
                self.style.ERROR(
                    '❌ ERROR: Esta operación es destructiva y no se puede deshacer.\n'
                    '   Para ejecutar, usa: --confirm'
                )
            )
            self.stdout.write('='*80 + '\n')
            return

        if dry_run:
            self.stdout.write('\n' + self.style.WARNING('🔍 MODO DRY-RUN: No se realizarán cambios'))
            return

        # Confirmación final
        self.stdout.write('\n' + '='*80)
        self.stdout.write(
            self.style.ERROR(
                '⚠️  ADVERTENCIA FINAL: Estás a punto de borrar TODOS los usuarios '
                'excepto admin y TODOS sus elementos asociados.\n'
                '   Esta operación NO SE PUEDE DESHACER.\n'
            )
        )
        self.stdout.write('='*80)

        # Ejecutar borrado
        self.stdout.write('\n🗑️  Iniciando borrado en cascada...\n')

        try:
            with transaction.atomic():
                deleted_count = 0
                errors = []

                for usuario in usuarios_a_borrar:
                    try:
                        usuario_username = usuario.username
                        usuario_id = usuario.id
                        
                        self.stdout.write(f'   Borrando usuario: {usuario_username} (ID: {usuario_id})...')
                        
                        if not skip_related:
                            # Limpiar relaciones ManyToMany primero (necesario antes de borrar)
                            usuario.groups.clear()
                            usuario.user_permissions.clear()
                            
                            # Borrar elementos que tienen relaciones específicas o que pueden causar problemas
                            # Nota: Django CASCADE manejará automáticamente la mayoría de relaciones
                            
                            # 1. Borrar OfertasServicio del usuario (a través de taller o mecanico)
                            # OfertaServicio tiene relaciones con Taller y MecanicoDomicilio, no directamente con Usuario
                            ofertas_count = 0
                            if hasattr(usuario, 'taller'):
                                ofertas_taller = OfertaServicio.objects.filter(taller=usuario.taller)
                                ofertas_count += ofertas_taller.count()
                                ofertas_taller.delete()
                            if hasattr(usuario, 'mecanico_domicilio'):
                                ofertas_mecanico = OfertaServicio.objects.filter(mecanico=usuario.mecanico_domicilio)
                                ofertas_count += ofertas_mecanico.count()
                                ofertas_mecanico.delete()
                            if ofertas_count > 0:
                                self.stdout.write(f'      ✅ {ofertas_count} ofertas de servicio borradas')
                            
                            # 2. Borrar SolicitudesServicioPublica creadas por el usuario
                            solicitudes_publicas_count = SolicitudServicioPublica.objects.filter(
                                cliente__usuario=usuario
                            ).count()
                            if solicitudes_publicas_count > 0:
                                SolicitudServicioPublica.objects.filter(cliente__usuario=usuario).delete()
                                self.stdout.write(f'      ✅ {solicitudes_publicas_count} solicitudes públicas borradas')
                            
                            # 3. Borrar CarritosAgendamiento
                            carritos_count = CarritoAgendamiento.objects.filter(
                                cliente__usuario=usuario
                            ).count()
                            if carritos_count > 0:
                                CarritoAgendamiento.objects.filter(cliente__usuario=usuario).delete()
                                self.stdout.write(f'      ✅ {carritos_count} carritos borrados')
                            
                            # 4. Borrar AlertasDescartadas
                            alertas_count = AlertaDescartada.objects.filter(usuario=usuario).count()
                            if alertas_count > 0:
                                AlertaDescartada.objects.filter(usuario=usuario).delete()
                                self.stdout.write(f'      ✅ {alertas_count} alertas descartadas borradas')
                            
                            # 5. Borrar recomendaciones personalizadas (a través de cliente)
                            recomendaciones_count = 0
                            if hasattr(usuario, 'cliente'):
                                recomendaciones_count = RecomendacionPersonalizada.objects.filter(cliente=usuario.cliente).count()
                                if recomendaciones_count > 0:
                                    RecomendacionPersonalizada.objects.filter(cliente=usuario.cliente).delete()
                                    self.stdout.write(f'      ✅ {recomendaciones_count} recomendaciones borradas')
                            
                            # 6. Borrar VehiculoActivo (a través de cliente)
                            vehiculos_activos_count = 0
                            if hasattr(usuario, 'cliente'):
                                vehiculos_activos_count = VehiculoActivo.objects.filter(cliente=usuario.cliente).count()
                                if vehiculos_activos_count > 0:
                                    VehiculoActivo.objects.filter(cliente=usuario.cliente).delete()
                                    self.stdout.write(f'      ✅ {vehiculos_activos_count} vehículos activos borrados')
                            
                            # 7. Borrar AuditAccesoCliente
                            audit_count = AuditAccesoCliente.objects.filter(usuario_proveedor=usuario).count()
                            if audit_count > 0:
                                AuditAccesoCliente.objects.filter(usuario_proveedor=usuario).delete()
                                self.stdout.write(f'      ✅ {audit_count} registros de auditoría borrados')
                            
                            # 8. Borrar ChecklistAuditLog (si existe en la base de datos)
                            # Nota: Este modelo puede no estar definido en el código pero existe en la BD
                            try:
                                from django.db import connection
                                with connection.cursor() as cursor:
                                    cursor.execute(
                                        "SELECT COUNT(*) FROM checklists_checklistauditlog WHERE usuario_id = %s",
                                        [usuario.id]
                                    )
                                    checklist_audit_count = cursor.fetchone()[0]
                                    if checklist_audit_count > 0:
                                        cursor.execute(
                                            "DELETE FROM checklists_checklistauditlog WHERE usuario_id = %s",
                                            [usuario.id]
                                        )
                                        self.stdout.write(f'      ✅ {checklist_audit_count} registros de auditoría de checklist borrados')
                            except Exception as e:
                                # Si la tabla no existe o hay algún error, continuar
                                logger.warning(f'No se pudo borrar ChecklistAuditLog: {str(e)}')
                            
                            # Nota: Los siguientes se borran automáticamente con CASCADE cuando se borra el usuario:
                            # - Cliente (OneToOne CASCADE) -> Vehiculos, SolicitudesServicio, etc.
                            # - Taller (OneToOne CASCADE) -> DocumentosOnboarding, etc.
                            # - MecanicoDomicilio (OneToOne CASCADE) -> DocumentosOnboarding, etc.
                            # - DireccionUsuario (ForeignKey CASCADE)
                            # - Pago (ForeignKey CASCADE)
                            # - PreferenciaPago (ForeignKey CASCADE)
                            # - CuentaMercadoPagoProveedor (OneToOne CASCADE)
                            # - CreditoProveedor (OneToOne CASCADE)
                            # - CompraCreditos (ForeignKey CASCADE)
                            # - ProveedorCancelaciones (OneToOne CASCADE)
                            # - ProviderProfile (OneToOne CASCADE)
                        
                        # Borrar el usuario (Django CASCADE borrará automáticamente todo lo relacionado)
                        usuario.delete()
                        deleted_count += 1
                        self.stdout.write(f'      ✅ Usuario {usuario_username} borrado completamente')
                        
                    except Exception as e:
                        error_msg = f'Error borrando usuario {usuario.username}: {str(e)}'
                        errors.append(error_msg)
                        self.stdout.write(
                            self.style.ERROR(f'      ❌ {error_msg}')
                        )
                        logger.error(error_msg, exc_info=True)

                # Resumen final
                self.stdout.write('\n' + '='*80)
                self.stdout.write(self.style.SUCCESS(f'✅ Borrado completado'))
                self.stdout.write('='*80)
                self.stdout.write(f'\n📊 Resumen:')
                self.stdout.write(f'   - Usuarios borrados: {deleted_count}/{total_usuarios}')
                
                if errors:
                    self.stdout.write(f'\n⚠️  Errores encontrados: {len(errors)}')
                    for error in errors:
                        self.stdout.write(f'   - {error}')
                else:
                    self.stdout.write(f'   - Errores: 0')
                
                self.stdout.write(f'\n✅ Usuario admin preservado: {admin_username}')
                self.stdout.write('')

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'\n❌ Error crítico durante el borrado: {str(e)}')
            )
            logger.error('Error crítico durante borrado de usuarios', exc_info=True)
            raise
