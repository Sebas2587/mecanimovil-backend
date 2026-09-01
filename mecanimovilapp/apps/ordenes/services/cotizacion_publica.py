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
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
    mano_obra_lineas_publicas as _mano_obra_lineas_publicas,
)
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
    descuento_visible_clp,
    etiqueta_descuento,
)
from mecanimovilapp.apps.vehiculos.cilindraje_texto import cilindraje_efectivo

from mecanimovilapp.apps.usuarios.legal_constants import (
    COTIZACION_PUBLICA_TTL_DAYS,
    POLITICAS_COTIZACION_FALLBACK,
)
from mecanimovilapp.storage.utils import get_image_url

logger = logging.getLogger(__name__)


def _foto_perfil_taller(taller, request=None) -> str | None:
    """Logo del taller: foto del proveedor, o la del usuario si solo está ahí."""
    if not taller:
        return None
    url = get_image_url(getattr(taller, 'foto_perfil', None), request)
    if url:
        return url
    usuario = getattr(taller, 'usuario', None)
    if usuario:
        return get_image_url(getattr(usuario, 'foto_perfil', None), request)
    return None


def _base_url_publica() -> str:
    return (
        getattr(settings, 'INFORME_PUBLIC_BASE_URL', '')
        or 'https://mecanimovil-usuarios.vercel.app'
    ).rstrip('/')


def construir_url_publica_cotizacion(token: str) -> str:
    return f'{_base_url_publica()}/cotizacion/{token}'


def resolver_dias_validez(*, taller=None, dias=None) -> int:
    """Override de la cotización → default del taller → 30 días."""
    for candidate in (dias, getattr(taller, 'dias_validez_cotizacion', None) if taller else None):
        try:
            n = int(candidate)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= 90:
            return n
    return COTIZACION_PUBLICA_TTL_DAYS


def snapshot_dias_validez(taller=None, override=None) -> int:
    return resolver_dias_validez(taller=taller, dias=override)


def aplicar_fecha_expiracion_publica(cotizacion: CotizacionCanal, *, desde=None) -> None:
    """fecha_expiracion_publica = enviada_en (o ahora) + dias_validez."""
    dias = resolver_dias_validez(
        taller=cotizacion.taller,
        dias=getattr(cotizacion, 'dias_validez', None),
    )
    cotizacion.dias_validez = dias
    base = desde or cotizacion.enviada_en or timezone.now()
    cotizacion.fecha_expiracion_publica = base + timezone.timedelta(days=dias)


def resolver_politicas_cotizacion(*, taller=None, texto: str | None = None) -> str:
    """Override de la cotización → default del taller → fallback de plataforma."""
    for candidate in (texto, getattr(taller, 'politicas_cotizacion', None) if taller else None):
        cleaned = (candidate or '').strip()
        if cleaned:
            return cleaned
    return POLITICAS_COTIZACION_FALLBACK


def asegurar_politicas_cotizacion(cotizacion: CotizacionCanal) -> CotizacionCanal:
    """Congela políticas en la cotización si aún no tiene snapshot."""
    if (cotizacion.politicas_cotizacion or '').strip():
        return cotizacion
    cotizacion.politicas_cotizacion = resolver_politicas_cotizacion(taller=cotizacion.taller)
    cotizacion.save(update_fields=['politicas_cotizacion', 'actualizado_en'])
    return cotizacion


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
        aplicar_fecha_expiracion_publica(cotizacion)
        update_fields.append('fecha_expiracion_publica')
        if 'dias_validez' not in update_fields:
            update_fields.append('dias_validez')
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
        pub = {
            k: v
            for k, v in item.items()
            if k not in ('tienda_ml', 'proveedor_nombre', 'url_producto')
        }
        out.append(pub)
    return out


def _servicio_principal_publico(cotizacion: CotizacionCanal) -> dict | None:
    if not cotizacion.es_cotizacion_adicional:
        return None
    nombre = ''
    orig = cotizacion.cotizacion_original
    if orig is not None:
        nombre = (orig.servicio_nombre or '').strip()
    if not nombre:
        cita = cotizacion.cita_origen
        det = getattr(cita, 'detalle', None) if cita is not None else None
        if det is not None:
            nombre = (det.servicio_nombre or '').strip()
    return {
        'nombre': nombre or 'Servicio en curso',
        'modalidad': cotizacion.modalidad,
    }


def formatear_numero_publico(pk: int) -> str:
    return f'MM-{int(pk):06d}'


def asegurar_numero_publico(cotizacion: CotizacionCanal) -> CotizacionCanal:
    """Asigna folio inmutable MM-000184. No pisa un valor existente."""
    if (cotizacion.numero_publico or '').strip():
        return cotizacion
    if cotizacion.pk is None:
        cotizacion.save()
    cotizacion.numero_publico = formatear_numero_publico(cotizacion.pk)
    cotizacion.save(update_fields=['numero_publico', 'actualizado_en'])
    return cotizacion


def _email_taller(taller) -> str:
    if not taller:
        return ''
    usuario = getattr(taller, 'usuario', None)
    return ((getattr(usuario, 'email', None) or '') if usuario else '').strip()


def _direccion_taller(taller) -> str:
    if not taller:
        return ''
    direccion_fisica = getattr(taller, 'direccion_fisica', None)
    if direccion_fisica is None:
        return ''
    return (getattr(direccion_fisica, 'direccion_completa', None) or '').strip()


def construir_emisor_snapshot(taller, request=None) -> dict:
    if not taller:
        return {}
    return {
        'nombre': (getattr(taller, 'nombre', None) or '').strip(),
        'telefono': (getattr(taller, 'telefono', None) or '').strip(),
        'email': _email_taller(taller),
        'direccion': _direccion_taller(taller),
        'foto_perfil': _foto_perfil_taller(taller, request),
        'verificado': bool(getattr(taller, 'verificado', False)),
        'calificacion_promedio': float(getattr(taller, 'calificacion_promedio', 0) or 0),
    }


def persistir_emisor_snapshot(cotizacion: CotizacionCanal, request=None) -> CotizacionCanal:
    cotizacion.emisor_snapshot = construir_emisor_snapshot(cotizacion.taller, request)
    cotizacion.save(update_fields=['emisor_snapshot', 'actualizado_en'])
    return cotizacion


def _contacto_canal(cotizacion: CotizacionCanal):
    conv = getattr(cotizacion, 'conversation', None)
    return getattr(conv, 'external_contact', None) if conv else None


def rellenar_cliente_desde_canal(cotizacion: CotizacionCanal) -> CotizacionCanal:
    """Completa nombre/teléfono vacíos desde el contacto omnicanal."""
    contact = _contacto_canal(cotizacion)
    if contact is None:
        return cotizacion
    update_fields: list[str] = []
    if not (cotizacion.cliente_nombre or '').strip():
        nombre = (getattr(contact, 'display_name', None) or '').strip()
        if nombre:
            cotizacion.cliente_nombre = nombre[:200]
            update_fields.append('cliente_nombre')
    if not (cotizacion.cliente_telefono or '').strip():
        tel = ''
        if hasattr(contact, 'telefono_efectivo'):
            tel = (contact.telefono_efectivo() or '').strip()
        if not tel:
            tel = (getattr(contact, 'phone', None) or '').strip()
        if tel:
            cotizacion.cliente_telefono = tel[:20]
            update_fields.append('cliente_telefono')
    if update_fields:
        update_fields.append('actualizado_en')
        cotizacion.save(update_fields=update_fields)
    return cotizacion


def preparar_emision_publica(cotizacion: CotizacionCanal, request=None) -> CotizacionCanal:
    """Token, folio, destinatario de canal y snapshot del taller."""
    asegurar_token_cotizacion(cotizacion)
    aplicar_fecha_expiracion_publica(cotizacion)
    if cotizacion.pk:
        cotizacion.save(update_fields=['dias_validez', 'fecha_expiracion_publica', 'actualizado_en'])
    asegurar_numero_publico(cotizacion)
    asegurar_politicas_cotizacion(cotizacion)
    rellenar_cliente_desde_canal(cotizacion)
    persistir_emisor_snapshot(cotizacion, request)
    return cotizacion


def _cliente_publico(cotizacion: CotizacionCanal) -> dict:
    nombre = (cotizacion.cliente_nombre or '').strip()
    telefono = (cotizacion.cliente_telefono or '').strip()
    if not nombre or not telefono:
        contact = _contacto_canal(cotizacion)
        if contact is not None:
            if not nombre:
                nombre = (getattr(contact, 'display_name', None) or '').strip()
            if not telefono:
                if hasattr(contact, 'telefono_efectivo'):
                    telefono = (contact.telefono_efectivo() or '').strip()
                if not telefono:
                    telefono = (getattr(contact, 'phone', None) or '').strip()
    direccion = (cotizacion.direccion_servicio or '').strip()
    out: dict = {}
    if nombre:
        out['nombre'] = nombre
    if telefono:
        out['telefono'] = telefono
    if direccion:
        out['direccion'] = direccion
    return out


def _taller_publico(cotizacion: CotizacionCanal, request=None) -> dict:
    snap = cotizacion.emisor_snapshot if isinstance(cotizacion.emisor_snapshot, dict) else {}
    if snap.get('nombre') or snap.get('telefono') or snap.get('email') or snap.get('direccion'):
        return {
            'nombre': str(snap.get('nombre') or ''),
            'telefono': str(snap.get('telefono') or ''),
            'email': str(snap.get('email') or ''),
            'direccion': str(snap.get('direccion') or ''),
            'foto_perfil': snap.get('foto_perfil') or None,
            'verificado': bool(snap.get('verificado')),
            'calificacion_promedio': float(snap.get('calificacion_promedio') or 0),
        }
    live = construir_emisor_snapshot(cotizacion.taller, request)
    return {
        'nombre': live.get('nombre') or '',
        'telefono': live.get('telefono') or '',
        'email': live.get('email') or '',
        'direccion': live.get('direccion') or '',
        'foto_perfil': live.get('foto_perfil'),
        'verificado': bool(live.get('verificado')),
        'calificacion_promedio': float(live.get('calificacion_promedio') or 0),
    }


def serializar_cotizacion_publica(cotizacion: CotizacionCanal, request=None) -> dict:
    es_adicional = bool(cotizacion.es_cotizacion_adicional)
    cliente = _cliente_publico(cotizacion)
    mano = int(cotizacion.mano_obra_clp or 0)
    reps = int(cotizacion.costo_repuestos_clp or 0)
    total = int(cotizacion.total_clp or 0)
    desc_clp = descuento_visible_clp(
        costo_repuestos_clp=reps,
        mano_obra_clp=mano,
        total_clp=total,
        descuento_clp=int(cotizacion.descuento_clp or 0),
    )
    desc_etiqueta = etiqueta_descuento(
        descuento_tipo=cotizacion.descuento_tipo or '',
        descuento_alcance=cotizacion.descuento_alcance or 'mano_obra',
        descuento_valor=cotizacion.descuento_valor or 0,
        descuento_clp=desc_clp,
    )
    if desc_clp > 0 and not desc_etiqueta:
        desc_etiqueta = f'Descuento ${desc_clp:,}'.replace(',', '.')
    return {
        'id': cotizacion.id,
        'numero_publico': (cotizacion.numero_publico or '').strip() or None,
        'estado': cotizacion.estado,
        'modalidad': cotizacion.modalidad,
        'direccion_servicio': cotizacion.direccion_servicio or '',
        'servicio_nombre': cotizacion.servicio_nombre,
        'descripcion_problema': cotizacion.descripcion_problema,
        'notas_cotizacion': (cotizacion.notas_internas or '').strip(),
        'politicas_cotizacion': resolver_politicas_cotizacion(
            taller=cotizacion.taller,
            texto=cotizacion.politicas_cotizacion,
        ),
        'vehiculo_marca': cotizacion.vehiculo_marca,
        'vehiculo_modelo': cotizacion.vehiculo_modelo,
        'vehiculo_anio': cotizacion.vehiculo_anio,
        'vehiculo_patente': cotizacion.vehiculo_patente,
        'vehiculo_cilindraje': cotizacion.vehiculo_cilindraje,
        'tipo_motor_label': cotizacion.tipo_motor_label,
        'repuestos': _repuestos_publicos(cotizacion.repuestos or []),
        'mano_obra_lineas': _mano_obra_lineas_publicas(cotizacion),
        'mano_obra_clp': mano,
        'costo_repuestos_clp': reps,
        'descuento_tipo': (cotizacion.descuento_tipo or '').strip() or None,
        'descuento_alcance': cotizacion.descuento_alcance or 'mano_obra',
        'descuento_valor': float(cotizacion.descuento_valor or 0),
        'descuento_clp': desc_clp,
        'descuento_etiqueta': desc_etiqueta,
        'dias_validez': resolver_dias_validez(
            taller=cotizacion.taller,
            dias=getattr(cotizacion, 'dias_validez', None),
        ),
        'total_clp': total,
        'duracion_minutos_estimada': cotizacion.duracion_minutos_estimada,
        'enviada_en': cotizacion.enviada_en.isoformat() if cotizacion.enviada_en else None,
        'aceptada_en': cotizacion.aceptada_en.isoformat() if cotizacion.aceptada_en else None,
        'rechazada_en': cotizacion.rechazada_en.isoformat() if cotizacion.rechazada_en else None,
        'visto_en': cotizacion.visto_en.isoformat() if cotizacion.visto_en else None,
        'actualizado_en': (
            cotizacion.actualizado_en.isoformat() if cotizacion.actualizado_en else None
        ),
        'actualizada_por_taller': bool(
            (cotizacion.metadata or {}).get('actualizada_tras_aceptacion')
            or (cotizacion.metadata or {}).get('reabierta_por_taller')
            or (cotizacion.metadata or {}).get('reabierta_por_cliente')
            or (
                cotizacion.enviada_en
                and cotizacion.actualizado_en
                and cotizacion.actualizado_en > cotizacion.enviada_en
            )
        ),
        'fecha_expiracion_publica': (
            cotizacion.fecha_expiracion_publica.isoformat()
            if cotizacion.fecha_expiracion_publica else None
        ),
        'expirado': cotizacion_publica_expirada(cotizacion),
        'cliente_nombre': cotizacion.cliente_nombre,
        'cliente': cliente,
        'taller': _taller_publico(cotizacion, request),
        'puede_responder': cotizacion.estado == 'enviada',
        'es_trabajo_adicional': es_adicional,
        'motivo_servicio_adicional': (
            (cotizacion.motivo_servicio_adicional or '').strip() if es_adicional else None
        ),
        'servicio_principal': _servicio_principal_publico(cotizacion),
        'pago_directo_taller': True,
        'ejecucion_adicional': (
            (cotizacion.ejecucion_adicional or 'misma_visita') if es_adicional else None
        ),
        'fecha_propuesta': (
            cotizacion.fecha_propuesta.isoformat()
            if es_adicional and cotizacion.fecha_propuesta
            else None
        ),
        'hora_propuesta': (
            cotizacion.hora_propuesta.strftime('%H:%M')
            if es_adicional and cotizacion.hora_propuesta
            else None
        ),
    }


@transaction.atomic
def enviar_cotizacion_libre(cotizacion: CotizacionCanal) -> CotizacionCanal:
    """Marca cotización libre como enviada y garantiza link público."""
    if cotizacion.estado != 'borrador':
        raise ValueError('Solo se pueden enviar cotizaciones en borrador.')
    if not cotizacion.es_libre:
        raise ValueError('Use enviar_cotizacion_canal para cotizaciones con conversación.')
    from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
        validar_adicional_listo_para_enviar,
    )

    validar_adicional_listo_para_enviar(cotizacion)
    if not cotizacion.servicio_nombre.strip():
        raise ValueError('Indica el nombre del servicio.')
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
        validar_nombres_mano_obra_para_enviar,
    )
    mo_err = validar_nombres_mano_obra_para_enviar(cotizacion)
    if mo_err:
        raise ValueError(mo_err)
    if not cotizacion.cliente_nombre.strip():
        raise ValueError('Indica el nombre del cliente.')

    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
        aplicar_totales_cotizacion,
    )

    aplicar_totales_cotizacion(cotizacion)
    cotizacion.estado = 'enviada'
    cotizacion.enviada_en = timezone.now()
    preparar_emision_publica(cotizacion)
    from mecanimovilapp.apps.ordenes.services.cotizacion_canal import cerrar_reapertura_taller

    cerrar_reapertura_taller(cotizacion)
    cotizacion.save(
        update_fields=[
            'costo_repuestos_clp',
            'mano_obra_clp',
            'descuento_clp',
            'total_clp',
            'estado',
            'enviada_en',
            'token',
            'url_publica',
            'fecha_expiracion_publica',
            'numero_publico',
            'emisor_snapshot',
            'politicas_cotizacion',
            'dias_validez',
            'cliente_nombre',
            'cliente_telefono',
            'metadata',
            'actualizado_en',
        ],
    )
    try:
        from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.aprendizaje_cotizacion import (
            registrar_cotizacion_enviada,
        )

        registrar_cotizacion_enviada(cotizacion)
    except Exception:
        pass
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
def aceptar_cotizacion_publica(cotizacion: CotizacionCanal) -> tuple[CotizacionCanal, CitaAgendaPersonal | None]:
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

    from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
        aplicar_adicional_aceptada_a_cita,
        crear_cita_desde_adicional_nueva_fecha,
        es_adicional_nueva_fecha,
    )

    if cotizacion.es_cotizacion_adicional:
        cita = cotizacion.cita_origen
        if cita is None:
            meta = cotizacion.metadata if isinstance(cotizacion.metadata, dict) else {}
            meta_cita_id = meta.get('cita_personal_id')
            if meta_cita_id:
                cita = CitaAgendaPersonal.objects.filter(pk=meta_cita_id).first()
                if cita is not None:
                    cotizacion.cita_origen = cita
                    cotizacion.save(update_fields=['cita_origen', 'actualizado_en'])
        if cita is None or cita.estado != 'activa':
            raise ValueError('El servicio principal ya no está activo para asociar este trabajo adicional.')
        if es_adicional_nueva_fecha(cotizacion):
            cita = crear_cita_desde_adicional_nueva_fecha(cotizacion, cita)
        else:
            aplicar_adicional_aceptada_a_cita(cotizacion, cita)
    else:
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
        from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
            cotizacion_es_trabajo_adicional,
        )

        if conv and isinstance(conv, Conversation) and not cotizacion_es_trabajo_adicional(cotizacion):
            from mecanimovilapp.apps.agente_ia.tasks import (
                aprender_conversacion_exitosa_task,
                iniciar_agendamiento_task,
            )

            aprender_conversacion_exitosa_task.delay(cotizacion.id)
            iniciar_agendamiento_task.delay(cotizacion.id)
        elif conv and isinstance(conv, Conversation):
            from mecanimovilapp.apps.agente_ia.tasks import aprender_conversacion_exitosa_task

            aprender_conversacion_exitosa_task.delay(cotizacion.id)
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
