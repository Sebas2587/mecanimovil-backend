"""Exportación de datos del titular (portabilidad ARCOP)."""
from __future__ import annotations

from django.utils import timezone

from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.ordenes.models import SolicitudServicio
from mecanimovilapp.apps.pagos.models import Pago
from mecanimovilapp.apps.usuarios.models import (
    Cliente,
    ConsentimientoUsuario,
    DireccionUsuario,
    PreferenciasNotificacion,
    Resena,
    Usuario,
)
from mecanimovilapp.apps.vehiculos.models import Vehiculo


def _serializar_usuario(usuario: Usuario) -> dict:
    return {
        'id': usuario.id,
        'username': usuario.username,
        'email': usuario.email,
        'first_name': usuario.first_name,
        'last_name': usuario.last_name,
        'telefono': usuario.telefono,
        'direccion': usuario.direccion,
        'fecha_registro': usuario.date_joined.isoformat() if usuario.date_joined else None,
    }


def _serializar_cliente(cliente: Cliente) -> dict:
    return {
        'nombre': cliente.nombre,
        'apellido': cliente.apellido,
        'email': cliente.email,
        'telefono': cliente.telefono,
        'direccion': cliente.direccion,
        'fecha_registro': cliente.fecha_registro.isoformat() if cliente.fecha_registro else None,
    }


def exportar_datos_usuario(usuario: Usuario) -> dict:
    cliente = getattr(usuario, 'cliente', None)

    vehiculos = []
    if cliente is not None:
        for v in Vehiculo.objects.filter(cliente=cliente).select_related('marca', 'modelo'):
            vehiculos.append({
                'id': v.id,
                'patente': v.patente,
                'marca': v.marca_nombre,
                'modelo': v.modelo_nombre,
                'anio': v.year,
                'kilometraje': v.kilometraje,
                'vin': v.vin,
            })

    ordenes = []
    if cliente is not None:
        for o in SolicitudServicio.objects.filter(cliente=cliente).order_by('-fecha_hora_solicitud')[:200]:
            ordenes.append({
                'id': o.id,
                'estado': o.estado,
                'tipo_servicio': o.tipo_servicio,
                'fecha_solicitud': o.fecha_hora_solicitud.isoformat() if o.fecha_hora_solicitud else None,
                'precio_total': str(o.total) if o.total is not None else None,
            })

    pagos = []
    for p in Pago.objects.filter(usuario=usuario).order_by('-fecha_creacion')[:200]:
        pagos.append({
            'id': str(p.id),
            'estado': p.status,
            'monto': str(p.transaction_amount) if p.transaction_amount is not None else None,
            'moneda': p.currency_id,
            'fecha_creacion': p.fecha_creacion.isoformat() if p.fecha_creacion else None,
        })

    direcciones = [
        {
            'etiqueta': d.etiqueta,
            'direccion': d.direccion,
            'detalles': d.detalles,
            'es_principal': d.es_principal,
        }
        for d in DireccionUsuario.objects.filter(usuario=usuario)
    ]

    conversaciones = []
    conv_qs = Conversation.objects.filter(participants=usuario).distinct()[:50]
    for conv in conv_qs:
        msgs = Message.objects.filter(conversation=conv).order_by('created_at')[:100]
        conversaciones.append({
            'id': conv.id,
            'mensajes': [
                {
                    'id': m.id,
                    'contenido': m.content,
                    'fecha': m.timestamp.isoformat() if m.timestamp else None,
                    'remitente_id': m.sender_id,
                }
                for m in msgs
            ],
        })

    resenas = []
    if cliente is not None:
        for r in Resena.objects.filter(cliente=cliente).order_by('-fecha_hora_resena')[:100]:
            resenas.append({
                'id': r.id,
                'calificacion': r.calificacion,
                'comentario': r.comentario,
                'fecha': r.fecha_hora_resena.isoformat() if r.fecha_hora_resena else None,
            })

    consentimientos = [
        {
            'tipo': c.tipo,
            'version': c.version_documento,
            'canal': c.canal,
            'fecha': c.fecha_aceptacion.isoformat(),
        }
        for c in ConsentimientoUsuario.objects.filter(usuario=usuario).order_by('-fecha_aceptacion')
    ]

    prefs = None
    try:
        p = usuario.preferencias_notificacion
        prefs = {
            'push_operativo': p.push_operativo,
            'push_marketing': p.push_marketing,
            'email_marketing': p.email_marketing,
        }
    except PreferenciasNotificacion.DoesNotExist:
        prefs = {
            'push_operativo': True,
            'push_marketing': False,
            'email_marketing': False,
        }

    return {
        'exportado_en': timezone.now().isoformat(),
        'formato': 'json',
        'version': '1.0',
        'usuario': _serializar_usuario(usuario),
        'cliente': _serializar_cliente(cliente) if cliente else None,
        'direcciones': direcciones,
        'vehiculos': vehiculos,
        'ordenes': ordenes,
        'pagos': pagos,
        'conversaciones': conversaciones,
        'resenas': resenas,
        'consentimientos': consentimientos,
        'preferencias_notificacion': prefs,
    }
