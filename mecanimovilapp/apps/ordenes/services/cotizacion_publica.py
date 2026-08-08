"""Cotizaciones libres con link público (sin conversación omnicanal)."""
from __future__ import annotations

import logging
import secrets
from datetime import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from mecanimovilapp.apps.ordenes.models import (
    CitaAgendaPersonal,
    CitaAgendaPersonalDetalle,
    CotizacionCanal,
)
from mecanimovilapp.apps.vehiculos.cilindraje_texto import cilindraje_efectivo

from mecanimovilapp.apps.usuarios.legal_constants import COTIZACION_PUBLICA_TTL_DAYS

logger = logging.getLogger(__name__)


def _base_url_publica() -> str:
    return (
        getattr(settings, 'INFORME_PUBLIC_BASE_URL', '')
        or 'https://mecanimovil-usuarios.vercel.app'
    ).rstrip('/')


def construir_url_publica_cotizacion(token: str) -> str:
    return f'{_base_url_publica()}/cotizacion/{token}'


def asegurar_token_cotizacion(cotizacion: CotizacionCanal) -> CotizacionCanal:
    """Genera token, URL pública y fecha de expiración si aún no existen."""
    update_fields: list[str] = []
    if not cotizacion.token:
        cotizacion.token = secrets.token_urlsafe(24)
        update_fields.append('token')
    if not cotizacion.url_publica and cotizacion.token:
        cotizacion.url_publica = construir_url_publica_cotizacion(cotizacion.token)
        update_fields.append('url_publica')
    if not cotizacion.fecha_expiracion_publica:
        cotizacion.fecha_expiracion_publica = timezone.now() + timezone.timedelta(
            days=COTIZACION_PUBLICA_TTL_DAYS,
        )
        update_fields.append('fecha_expiracion_publica')
    if update_fields:
        update_fields.append('actualizado_en')
        cotizacion.save(update_fields=update_fields)
    return cotizacion


def cotizacion_publica_expirada(cotizacion: CotizacionCanal) -> bool:
    if cotizacion.estado == 'expirada':
        return True
    if cotizacion.fecha_expiracion_publica and timezone.now() > cotizacion.fecha_expiracion_publica:
        return True
    return False


def marcar_cotizacion_expirada_si_corresponde(cotizacion: CotizacionCanal) -> CotizacionCanal:
    if cotizacion_publica_expirada(cotizacion) and cotizacion.estado == 'enviada':
        cotizacion.estado = 'expirada'
        cotizacion.save(update_fields=['estado', 'actualizado_en'])
    return cotizacion


def marcar_visto(cotizacion: CotizacionCanal) -> CotizacionCanal:
    era_nueva_vista = cotizacion.visto_en is None and cotizacion.estado == 'enviada'
    if era_nueva_vista:
        cotizacion.visto_en = timezone.now()
        cotizacion.save(update_fields=['visto_en', 'actualizado_en'])
        from mecanimovilapp.apps.agente_ia.services.lead_scoring import (
            actualizar_calificacion_desde_cotizacion,
        )
        actualizar_calificacion_desde_cotizacion(cotizacion, evento='vista')
    return cotizacion


def _repuestos_publicos(repuestos: list | None) -> list[dict]:
    """Repuestos para vista pública del cliente (sin datos internos del taller)."""
    out: list[dict] = []
    for item in repuestos or []:
        if not isinstance(item, dict):
            continue
        pub = {k: v for k, v in item.items() if k != 'tienda_ml'}
        out.append(pub)
    return out


def serializar_cotizacion_publica(cotizacion: CotizacionCanal) -> dict:
    taller = cotizacion.taller
    # direccion_fisica es reverse OneToOne: no existe taller.direccion_fisica_id
    direccion_fisica = getattr(taller, 'direccion_fisica', None) if taller else None
    foto_perfil = getattr(taller, 'foto_perfil', None) if taller else None
    return {
        'id': cotizacion.id,
        'estado': cotizacion.estado,
        'modalidad': cotizacion.modalidad,
        'direccion_servicio': cotizacion.direccion_servicio or '',
        'servicio_nombre': cotizacion.servicio_nombre,
        'descripcion_problema': cotizacion.descripcion_problema,
        'vehiculo_marca': cotizacion.vehiculo_marca,
        'vehiculo_modelo': cotizacion.vehiculo_modelo,
        'vehiculo_anio': cotizacion.vehiculo_anio,
        'vehiculo_patente': cotizacion.vehiculo_patente,
        'vehiculo_cilindraje': cotizacion.vehiculo_cilindraje,
        'tipo_motor_label': cotizacion.tipo_motor_label,
        'repuestos': _repuestos_publicos(cotizacion.repuestos or []),
        'mano_obra_clp': int(cotizacion.mano_obra_clp or 0),
        'costo_repuestos_clp': int(cotizacion.costo_repuestos_clp or 0),
        'total_clp': int(cotizacion.total_clp or 0),
        'duracion_minutos_estimada': cotizacion.duracion_minutos_estimada,
        'enviada_en': cotizacion.enviada_en.isoformat() if cotizacion.enviada_en else None,
        'aceptada_en': cotizacion.aceptada_en.isoformat() if cotizacion.aceptada_en else None,
        'rechazada_en': cotizacion.rechazada_en.isoformat() if cotizacion.rechazada_en else None,
        'visto_en': cotizacion.visto_en.isoformat() if cotizacion.visto_en else None,
        'fecha_expiracion_publica': (
            cotizacion.fecha_expiracion_publica.isoformat()
            if cotizacion.fecha_expiracion_publica else None
        ),
        'expirado': cotizacion_publica_expirada(cotizacion),
        'cliente_nombre': cotizacion.cliente_nombre,
        'taller': {
            'nombre': (getattr(taller, 'nombre', None) or '') if taller else '',
            'telefono': (getattr(taller, 'telefono', None) or '') if taller else '',
            'direccion': (
                (getattr(direccion_fisica, 'direccion_completa', None) or '')
                if direccion_fisica is not None
                else ''
            ),
            'foto_perfil': foto_perfil.url if foto_perfil else None,
        },
        'puede_responder': cotizacion.estado == 'enviada',
    }


@transaction.atomic
def enviar_cotizacion_libre(cotizacion: CotizacionCanal) -> CotizacionCanal:
    """Marca cotización libre como enviada y garantiza link público."""
    if cotizacion.estado != 'borrador':
        raise ValueError('Solo se pueden enviar cotizaciones en borrador.')
    if not cotizacion.es_libre:
        raise ValueError('Use enviar_cotizacion_canal para cotizaciones con conversación.')
    if not cotizacion.servicio_nombre.strip():
        raise ValueError('Indica el nombre del servicio.')
    if not cotizacion.cliente_nombre.strip():
        raise ValueError('Indica el nombre del cliente.')

    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import recalcular_totales

    costo_rep, mo, total = recalcular_totales(
        cotizacion.repuestos or [],
        int(cotizacion.mano_obra_clp or 0),
    )
    cotizacion.costo_repuestos_clp = costo_rep
    cotizacion.mano_obra_clp = mo
    cotizacion.total_clp = total
    cotizacion.estado = 'enviada'
    cotizacion.enviada_en = timezone.now()
    asegurar_token_cotizacion(cotizacion)
    cotizacion.save(
        update_fields=[
            'costo_repuestos_clp',
            'mano_obra_clp',
            'total_clp',
            'estado',
            'enviada_en',
            'token',
            'url_publica',
            'fecha_expiracion_publica',
            'actualizado_en',
        ],
    )
    from mecanimovilapp.apps.agente_ia.services.sesion_cotizacion import (
        liberar_sesiones_tras_cerrar_borrador,
    )

    liberar_sesiones_tras_cerrar_borrador(cotizacion)
    return cotizacion


@transaction.atomic
def _telefono_desde_cotizacion(cotizacion: CotizacionCanal) -> str:
    """Teléfono de cotización o, si falta, del contacto WhatsApp de la conversación."""
    tel = (cotizacion.cliente_telefono or '').strip()
    if tel:
        return tel[:20]
    conv = getattr(cotizacion, 'conversation', None)
    contact = getattr(conv, 'external_contact', None) if conv else None
    if contact is not None and hasattr(contact, 'telefono_efectivo'):
        return (contact.telefono_efectivo() or '')[:20]
    if contact is not None:
        return ((contact.phone or '') or '')[:20]
    return ''


@transaction.atomic
def crear_cita_desde_cotizacion_aceptada(cotizacion: CotizacionCanal) -> CitaAgendaPersonal:
    """Crea cita personal placeholder tras aceptación (horario por confirmar vía agente IA)."""
    duracion = cotizacion.duracion_minutos_estimada or 60
    tipo_servicio = 'domicilio' if cotizacion.modalidad == 'domicilio' else 'taller'
    direccion = (cotizacion.direccion_servicio or '').strip()[:500]
    tel_efectivo = _telefono_desde_cotizacion(cotizacion)
    ahora = timezone.now()

    cita = CitaAgendaPersonal(
        taller=cotizacion.taller,
        cotizacion_canal_origen=cotizacion,
        conversation_origen=cotizacion.conversation,
        fecha_servicio=ahora.date(),
        hora_servicio=time(8, 0),
        duracion_minutos=duracion,
        tipo_servicio=tipo_servicio,
        horario_por_confirmar=True,
        creado_por=cotizacion.creado_por,
    )
    if cita.creado_por_id is None:
        if cotizacion.creado_por_id:
            cita.creado_por = cotizacion.creado_por
        elif cotizacion.taller and cotizacion.taller.usuario_id:
            cita.creado_por_id = cotizacion.taller.usuario_id
    cita.full_clean()
    cita.save()

    det = CitaAgendaPersonalDetalle(
        cita=cita,
        cliente_nombre=cotizacion.cliente_nombre or 'Cliente',
        cliente_telefono=tel_efectivo or (cotizacion.cliente_telefono or ''),
        direccion=direccion,
        vehiculo_marca=cotizacion.vehiculo_marca,
        vehiculo_modelo=cotizacion.vehiculo_modelo,
        vehiculo_patente=cotizacion.vehiculo_patente,
        vehiculo_vin=(cotizacion.vehiculo_vin or '').strip().upper()[:30],
        vehiculo_anio=cotizacion.vehiculo_anio,
        vehiculo_cilindraje=cilindraje_efectivo(
            cotizacion.vehiculo_cilindraje,
            cotizacion.vehiculo_marca,
            cotizacion.vehiculo_modelo,
        ),
        servicio_nombre=cotizacion.servicio_nombre,
        descripcion=cotizacion.descripcion_problema,
        precio_referencia=cotizacion.total_clp,
    )
    det.full_clean()
    det.save()

    logger.info(
        'Cotización %s aceptada → cita personal %s (horario por confirmar, tipo=%s)',
        cotizacion.id,
        cita.id,
        tipo_servicio,
    )
    return cita


@transaction.atomic
def aceptar_cotizacion_publica(cotizacion: CotizacionCanal) -> tuple[CotizacionCanal, CitaAgendaPersonal]:
    if cotizacion.estado != 'enviada':
        raise ValueError('Esta cotización ya fue respondida.')

    ahora = timezone.now()
    cotizacion.estado = 'aceptada'
    cotizacion.aceptada_en = ahora

    # Rellena teléfono/VIN en la cotización si el borrador los dejó vacíos.
    tel_efectivo = _telefono_desde_cotizacion(cotizacion)
    update_cot = ['estado', 'aceptada_en', 'actualizado_en']
    if tel_efectivo and not (cotizacion.cliente_telefono or '').strip():
        cotizacion.cliente_telefono = tel_efectivo
        update_cot.append('cliente_telefono')
    cotizacion.save(update_fields=update_cot)

    cita = crear_cita_desde_cotizacion_aceptada(cotizacion)
    from mecanimovilapp.apps.agente_ia.services.lead_scoring import (
        actualizar_calificacion_desde_cotizacion,
    )
    actualizar_calificacion_desde_cotizacion(cotizacion, evento='aceptada')
    return cotizacion, cita


@transaction.atomic
def rechazar_cotizacion_publica(cotizacion: CotizacionCanal) -> CotizacionCanal:
    if cotizacion.estado != 'enviada':
        raise ValueError('Esta cotización ya fue respondida.')
    cotizacion.estado = 'rechazada'
    cotizacion.rechazada_en = timezone.now()
    cotizacion.save(update_fields=['estado', 'rechazada_en', 'actualizado_en'])
    from mecanimovilapp.apps.agente_ia.services.lead_scoring import (
        actualizar_calificacion_desde_cotizacion,
    )
    actualizar_calificacion_desde_cotizacion(cotizacion, evento='rechazada')
    return cotizacion


def on_cotizacion_respondida(
    cotizacion: CotizacionCanal,
    accion: str,
    *,
    conversation=None,
    cita_id: int | None = None,
) -> None:
    """Notifica al taller y encola tareas del agente tras aceptar/rechazar."""
    from mecanimovilapp.apps.chat.models import Conversation

    conv = conversation or cotizacion.conversation
    proveedor_id = cotizacion.creado_por_id
    if not proveedor_id and cotizacion.taller_id:
        proveedor_id = getattr(cotizacion.taller, 'usuario_id', None)

    if not proveedor_id:
        return

    conversation_id = conv.id if conv else cotizacion.conversation_id

    if accion == 'aceptar':
        from mecanimovilapp.apps.agente_ia.services.notificaciones import (
            notificar_cotizacion_aceptada_agente,
        )

        notificar_cotizacion_aceptada_agente(
            proveedor_user_id=proveedor_id,
            cotizacion=cotizacion,
            conversation_id=conversation_id or 0,
            cita_id=cita_id,
        )
        if conv and isinstance(conv, Conversation):
            from mecanimovilapp.apps.agente_ia.tasks import (
                aprender_conversacion_exitosa_task,
                iniciar_agendamiento_task,
            )

            aprender_conversacion_exitosa_task.delay(cotizacion.id)
            iniciar_agendamiento_task.delay(cotizacion.id)
    elif accion == 'rechazar':
        from mecanimovilapp.apps.agente_ia.services.notificaciones import (
            notificar_cotizacion_rechazada_agente,
        )

        notificar_cotizacion_rechazada_agente(
            proveedor_user_id=proveedor_id,
            cotizacion=cotizacion,
            conversation_id=conversation_id or 0,
        )
        if conv and isinstance(conv, Conversation):
            from mecanimovilapp.apps.agente_ia.tasks import reaccionar_rechazo_task

            reaccionar_rechazo_task.delay(cotizacion.id)
