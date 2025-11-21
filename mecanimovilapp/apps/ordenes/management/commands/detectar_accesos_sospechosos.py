from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count, Q
from django.core.mail import send_mail
from django.conf import settings
from mecanimovilapp.apps.ordenes.models import AuditAccesoCliente
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Detecta y reporta accesos sospechosos a información de clientes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help='Horas hacia atrás para analizar (default: 24)'
        )
        parser.add_argument(
            '--send-email',
            action='store_true',
            help='Enviar reporte por email a administradores'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Mostrar información detallada'
        )

    def handle(self, *args, **options):
        horas = options['hours']
        send_email = options['send_email']
        verbose = options['verbose']
        
        # Calcular fecha límite
        fecha_limite = timezone.now() - timedelta(hours=horas)
        
        self.stdout.write(
            self.style.SUCCESS(f'🔍 Analizando accesos de las últimas {horas} horas...')
        )
        
        # Detectar patrones sospechosos
        patrones_sospechosos = self.detectar_patrones_sospechosos(fecha_limite, verbose)
        
        # Generar reporte
        reporte = self.generar_reporte(patrones_sospechosos, horas)
        
        # Mostrar en consola
        self.stdout.write(reporte)
        
        # Enviar por email si se solicita
        if send_email:
            self.enviar_reporte_email(reporte, horas)
            
        # Actualizar flags de revisión
        self.actualizar_flags_revision(patrones_sospechosos)

    def detectar_patrones_sospechosos(self, fecha_limite, verbose):
        """
        Detecta diferentes patrones de comportamiento sospechoso
        """
        patrones = {}
        
        # 1. Accesos múltiples no autorizados
        accesos_no_autorizados = AuditAccesoCliente.objects.filter(
            fecha_acceso__gte=fecha_limite,
            acceso_autorizado=False
        ).count()
        
        if accesos_no_autorizados > 0:
            patrones['accesos_no_autorizados'] = {
                'count': accesos_no_autorizados,
                'descripcion': 'Accesos no autorizados detectados',
                'gravedad': 'alta' if accesos_no_autorizados > 10 else 'media'
            }
        
        # 2. Usuarios con accesos excesivos
        usuarios_excesivos = AuditAccesoCliente.objects.filter(
            fecha_acceso__gte=fecha_limite
        ).values('usuario_proveedor__username').annotate(
            total_accesos=Count('id')
        ).filter(total_accesos__gt=50).order_by('-total_accesos')
        
        if usuarios_excesivos.exists():
            patrones['usuarios_excesivos'] = {
                'usuarios': list(usuarios_excesivos),
                'descripcion': 'Usuarios con número excesivo de accesos',
                'gravedad': 'media'
            }
        
        # 3. Accesos fuera de horario laboral
        hora_actual = timezone.now().time()
        accesos_fuera_horario = AuditAccesoCliente.objects.filter(
            fecha_acceso__gte=fecha_limite,
            fecha_acceso__time__lt=timezone.time(6, 0),  # Antes de 6 AM
        ).count() + AuditAccesoCliente.objects.filter(
            fecha_acceso__gte=fecha_limite,
            fecha_acceso__time__gt=timezone.time(22, 0),  # Después de 10 PM
        ).count()
        
        if accesos_fuera_horario > 5:
            patrones['accesos_fuera_horario'] = {
                'count': accesos_fuera_horario,
                'descripcion': 'Accesos fuera del horario laboral normal',
                'gravedad': 'baja'
            }
        
        # 4. Múltiples IPs por usuario
        usuarios_multiples_ips = AuditAccesoCliente.objects.filter(
            fecha_acceso__gte=fecha_limite
        ).values('usuario_proveedor__username').annotate(
            ips_distintas=Count('ip_address', distinct=True)
        ).filter(ips_distintas__gt=3).order_by('-ips_distintas')
        
        if usuarios_multiples_ips.exists():
            patrones['usuarios_multiples_ips'] = {
                'usuarios': list(usuarios_multiples_ips),
                'descripcion': 'Usuarios accediendo desde múltiples IPs',
                'gravedad': 'media'
            }
        
        # 5. Contacto directo sin autorización
        contactos_directos = AuditAccesoCliente.objects.filter(
            fecha_acceso__gte=fecha_limite,
            tipo_acceso='contacto_directo',
            acceso_autorizado=False
        ).count()
        
        if contactos_directos > 0:
            patrones['contactos_directos_no_autorizados'] = {
                'count': contactos_directos,
                'descripcion': 'Intentos de contacto directo no autorizados',
                'gravedad': 'alta'
            }
        
        # 6. Accesos a órdenes cerradas
        accesos_ordenes_cerradas = AuditAccesoCliente.objects.filter(
            fecha_acceso__gte=fecha_limite,
            estado_orden_acceso__in=['completado', 'cancelado'],
            nivel_informacion='completo'
        ).count()
        
        if accesos_ordenes_cerradas > 0:
            patrones['accesos_ordenes_cerradas'] = {
                'count': accesos_ordenes_cerradas,
                'descripcion': 'Accesos completos a órdenes cerradas',
                'gravedad': 'alta'
            }
        
        if verbose:
            for patron, datos in patrones.items():
                self.stdout.write(f"🚨 Patrón detectado: {patron} - {datos['descripcion']}")
        
        return patrones

    def generar_reporte(self, patrones, horas):
        """
        Genera un reporte legible de los patrones detectados
        """
        if not patrones:
            return f"✅ No se detectaron patrones sospechosos en las últimas {horas} horas."
        
        reporte = f"🚨 REPORTE DE SEGURIDAD - ACCESOS SOSPECHOSOS\n"
        reporte += f"📅 Período analizado: Últimas {horas} horas\n"
        reporte += f"🕐 Generado: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        # Clasificar por gravedad
        alta_gravedad = [p for p in patrones.values() if p.get('gravedad') == 'alta']
        media_gravedad = [p for p in patrones.values() if p.get('gravedad') == 'media']
        baja_gravedad = [p for p in patrones.values() if p.get('gravedad') == 'baja']
        
        if alta_gravedad:
            reporte += "🔴 ALERTAS DE ALTA GRAVEDAD:\n"
            for patron in alta_gravedad:
                reporte += f"   • {patron['descripcion']}\n"
            reporte += "\n"
        
        if media_gravedad:
            reporte += "🟡 ALERTAS DE MEDIA GRAVEDAD:\n"
            for patron in media_gravedad:
                reporte += f"   • {patron['descripcion']}\n"
                if 'usuarios' in patron:
                    for usuario in patron['usuarios'][:5]:  # Mostrar solo los primeros 5
                        reporte += f"     - {usuario['usuario_proveedor__username']}: {usuario.get('total_accesos', usuario.get('ips_distintas', 'N/A'))} accesos/IPs\n"
            reporte += "\n"
        
        if baja_gravedad:
            reporte += "🟢 ALERTAS DE BAJA GRAVEDAD:\n"
            for patron in baja_gravedad:
                reporte += f"   • {patron['descripcion']}\n"
            reporte += "\n"
        
        reporte += f"📊 Total de patrones detectados: {len(patrones)}\n"
        reporte += f"⚠️  Recomendación: Revisar manualmente los accesos marcados como sospechosos.\n"
        
        return reporte

    def enviar_reporte_email(self, reporte, horas):
        """
        Envía el reporte por email a los administradores
        """
        try:
            send_mail(
                subject=f'🚨 Alerta de Seguridad - Accesos Sospechosos ({horas}h)',
                message=reporte,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[admin[1] for admin in settings.ADMINS],
                fail_silently=False,
            )
            self.stdout.write(
                self.style.SUCCESS("📧 Reporte enviado por email a administradores")
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Error enviando email: {str(e)}")
            )

    def actualizar_flags_revision(self, patrones):
        """
        Actualiza los flags de revisión para accesos sospechosos
        """
        fecha_limite = timezone.now() - timedelta(hours=24)
        
        # Marcar accesos no autorizados para revisión
        if 'accesos_no_autorizados' in patrones:
            AuditAccesoCliente.objects.filter(
                fecha_acceso__gte=fecha_limite,
                acceso_autorizado=False,
                requiere_revision=False
            ).update(requiere_revision=True)
        
        # Marcar contactos directos no autorizados
        if 'contactos_directos_no_autorizados' in patrones:
            AuditAccesoCliente.objects.filter(
                fecha_acceso__gte=fecha_limite,
                tipo_acceso='contacto_directo',
                acceso_autorizado=False,
                requiere_revision=False
            ).update(requiere_revision=True)
        
        # Marcar accesos a órdenes cerradas
        if 'accesos_ordenes_cerradas' in patrones:
            AuditAccesoCliente.objects.filter(
                fecha_acceso__gte=fecha_limite,
                estado_orden_acceso__in=['completado', 'cancelado'],
                nivel_informacion='completo',
                requiere_revision=False
            ).update(requiere_revision=True)
        
        self.stdout.write(
            self.style.SUCCESS("✅ Flags de revisión actualizados")
        ) 