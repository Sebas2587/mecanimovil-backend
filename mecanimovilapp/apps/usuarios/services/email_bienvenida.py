"""
Servicio de correo de bienvenida para nuevos usuarios de MecaniMovil.

Envía un email personalizado al registrarse (manual o Google) desde
cualquiera de las dos apps (proveedores o usuarios/clientes).
"""

import logging
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _email_configurado() -> bool:
    host_user = getattr(settings, 'EMAIL_HOST_USER', '')
    host_pass = getattr(settings, 'EMAIL_HOST_PASSWORD', '')
    return bool(host_user and host_pass)


def enviar_email_bienvenida_cliente(email: str, nombre: str) -> bool:
    """Envía correo de bienvenida a un cliente (app de usuarios)."""
    if not _email_configurado():
        logger.warning('EMAIL no configurado — omitiendo bienvenida cliente')
        return False

    asunto = 'Bienvenido a MecaniMovil'
    cuerpo = f"""Hola {nombre},

¡Bienvenido/a a MecaniMovil! Tu cuenta ha sido creada exitosamente.

Con tu cuenta podrás:

  • Buscar talleres y mecánicos a domicilio cerca de ti
  • Agendar servicios de mantenimiento y reparación
  • Recibir cotizaciones de múltiples proveedores
  • Gestionar tus vehículos y su historial de servicios
  • Seguir en tiempo real el estado de tus servicios
  • Evaluar y dejar reseñas a los proveedores
  • Acceder a promociones y descuentos exclusivos

Si tienes alguna pregunta o necesitas ayuda, no dudes en contactarnos.

¡Gracias por confiar en MecaniMovil!

— El equipo de MecaniMovil
"""
    return _enviar(asunto, cuerpo, email)


def enviar_email_bienvenida_proveedor(email: str, nombre: str) -> bool:
    """Envía correo de bienvenida a un proveedor (app de proveedores)."""
    if not _email_configurado():
        logger.warning('EMAIL no configurado — omitiendo bienvenida proveedor')
        return False

    asunto = 'Bienvenido a MecaniMovil — Portal de Proveedores'
    cuerpo = f"""Hola {nombre},

¡Bienvenido/a al Portal de Proveedores de MecaniMovil!

Tu cuenta ha sido creada. Al completar tu registro y verificación tendrás acceso a:

  • Recibir solicitudes de servicio de clientes cercanos
  • Gestionar tu equipo de trabajo (mecánicos, supervisores)
  • Configurar modalidades de atención (en taller, a domicilio o ambas)
  • Definir horarios por mecánico y especialidades
  • Asignación automática de servicios al mecánico más adecuado
  • Panel de rendimiento y KPIs por mecánico
  • Calendario integrado de citas y servicios
  • Gestionar tu catálogo de servicios y precios
  • Sistema de créditos para recibir órdenes de servicio

Próximos pasos:
  1. Completa tu perfil con datos de tu taller o servicio
  2. Sube los documentos requeridos para verificación
  3. Configura tus servicios, marcas y especialidades
  4. Nuestro equipo revisará tu información y te notificará

Si tienes preguntas, escríbenos y te ayudaremos.

¡Éxito con tu negocio en MecaniMovil!

— El equipo de MecaniMovil
"""
    return _enviar(asunto, cuerpo, email)


def _enviar(asunto: str, cuerpo: str, destinatario: str) -> bool:
    try:
        send_mail(
            subject=asunto,
            message=cuerpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[destinatario],
            fail_silently=False,
        )
        logger.info(f'Email de bienvenida enviado a {destinatario}')
        return True
    except Exception as exc:
        logger.error(f'Error enviando email de bienvenida a {destinatario}: {exc}')
        return False
