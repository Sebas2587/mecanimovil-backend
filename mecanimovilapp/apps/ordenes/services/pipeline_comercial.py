"""
Agregador de pipeline comercial unificado para proveedores.
Normaliza solicitudes, ofertas, cotizaciones de canal y citas personales.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Q
from django.utils import timezone

from mecanimovilapp.apps.chat.models import Conversation
from mecanimovilapp.apps.ordenes.models import (
    CitaAgendaPersonal,
    CotizacionCanal,
    OfertaProveedor,
    RechazoSolicitud,
    SolicitudServicio,
    SolicitudServicioPublica,
)
from mecanimovilapp.apps.usuarios.models import Taller

ESTADOS_NORMALIZADOS = (
    'nuevo',
    'cotizacion_enviada',
    'en_negociacion',
    'aceptado_agendado',
    'rechazado_perdido',
    'en_ejecucion',
    'completado',
)

OFERTA_ESTADO_MAP = {
    'enviada': 'cotizacion_enviada',
    'vista': 'cotizacion_enviada',
    'pendiente_confirmacion': 'cotizacion_enviada',
    'pendiente_creditos': 'cotizacion_enviada',
    'en_chat': 'en_negociacion',
    'aceptada': 'aceptado_agendado',
    'pendiente_pago': 'aceptado_agendado',
    'pagada_parcialmente': 'aceptado_agendado',
    'pagada': 'aceptado_agendado',
    'en_ejecucion': 'en_ejecucion',
    'completada': 'completado',
    'rechazada': 'rechazado_perdido',
    'retirada': 'rechazado_perdido',
    'expirada': 'rechazado_perdido',
}

COTIZACION_CANAL_MAP = {
    'borrador': 'nuevo',
    'enviada': 'cotizacion_enviada',
    # Aceptada ≠ agendada: falta confirmar día/hora/técnico.
    'aceptada': 'en_negociacion',
    'rechazada': 'rechazado_perdido',
    'expirada': 'rechazado_perdido',
    'cancelada': 'rechazado_perdido',
}

CITA_PERSONAL_MAP = {
    'activa': 'aceptado_agendado',
    'cerrada': 'completado',
    'cancelada': 'rechazado_perdido',
}

SOLICITUD_DIRECTA_MAP = {
    'pendiente': 'nuevo',
    'pago_validado': 'nuevo',
    'confirmado': 'aceptado_agendado',
    'pendiente_aceptacion_proveedor': 'nuevo',
    'aceptada_por_proveedor': 'aceptado_agendado',
    'rechazada_por_proveedor': 'rechazado_perdido',
    'checklist_en_progreso': 'en_ejecucion',
    'checklist_completado': 'en_ejecucion',
    'en_proceso': 'en_ejecucion',
    'pendiente_firma_cliente': 'en_ejecucion',
    'completado': 'completado',
    'cancelado': 'rechazado_perdido',
    'solicitud_cancelacion': 'rechazado_perdido',
    'pendiente_devolucion': 'rechazado_perdido',
    'devuelto': 'rechazado_perdido',
}

SOLICITUD_PUBLICA_MAP = {
    'creada': 'nuevo',
    'seleccionando_servicios': 'nuevo',
    'publicada': 'nuevo',
    'con_ofertas': 'cotizacion_enviada',
    'pendiente_confirmacion': 'cotizacion_enviada',
    'esperando_creditos_proveedor': 'cotizacion_enviada',
    'adjudicada': 'aceptado_agendado',
    'pendiente_pago': 'aceptado_agendado',
    'pagada': 'aceptado_agendado',
    'en_ejecucion': 'en_ejecucion',
    'completada': 'completado',
    'expirada': 'rechazado_perdido',
    'cancelada': 'rechazado_perdido',
}


def _canal_origen(conversation: Conversation | None) -> str:
    if conversation is None:
        return 'canal'
    channel = (conversation.source_channel or 'APP').lower()
    if channel == 'whatsapp':
        return 'whatsapp'
    if channel == 'instagram':
        return 'instagram'
    if channel == 'messenger':
        return 'messenger'
    return 'canal'


def _contacto_nombre(*parts: str | None) -> str:
    return ' '.join(p.strip() for p in parts if p and str(p).strip()).strip() or 'Cliente'


def _tiempo_en_estado(fecha_ref) -> int | None:
    if not fecha_ref:
        return None
    delta = timezone.now() - fecha_ref
    return max(0, int(delta.total_seconds() // 3600))


def _umbrales_silencio_lead(lead_categoria: str | None) -> tuple[int, int]:
    from mecanimovilapp.apps.agente_ia.services.lead_scoring import umbrales_seguimiento_por_lead

    return umbrales_seguimiento_por_lead(lead_categoria)


def _esperando_respuesta_24h(
    fecha_ref,
    estado_normalizado: str,
    lead_categoria: str | None = None,
) -> bool:
    if estado_normalizado != 'cotizacion_enviada':
        return False
    if not fecha_ref:
        return False
    horas_alerta, _ = _umbrales_silencio_lead(lead_categoria)
    return timezone.now() - fecha_ref >= timedelta(hours=horas_alerta)


def _demorado_48h(
    fecha_ref,
    estado_normalizado: str,
    lead_categoria: str | None = None,
) -> bool:
    if estado_normalizado != 'cotizacion_enviada':
        return False
    if not fecha_ref:
        return False
    _, horas_demorado = _umbrales_silencio_lead(lead_categoria)
    if horas_demorado >= 999:
        return False
    return timezone.now() - fecha_ref >= timedelta(hours=horas_demorado)


def _visto_sin_respuesta(estado_normalizado: str, visto_en) -> bool:
    return estado_normalizado == 'cotizacion_enviada' and visto_en is not None


def _monto_a_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _fila_base(
    *,
    tipo_entidad: str,
    entidad_id: str,
    origen: str,
    estado_normalizado: str,
    estado_raw: str,
    cliente_nombre: str,
    cliente_telefono: str = '',
    vehiculo_resumen: str = '',
    servicio_resumen: str = '',
    monto_clp: float | None = None,
    fecha_referencia,
    fecha_limite_respuesta=None,
    conversation_id: int | None = None,
    solicitud_id: str | None = None,
    oferta_id: str | None = None,
    orden_id: int | None = None,
    cita_id: int | None = None,
    cotizacion_id: int | None = None,
    miembro_taller_id: int | None = None,
    miembro_taller_nombre: str | None = None,
    template_generado_por_ia: bool = False,
    visto_sin_respuesta: bool = False,
    horario_por_confirmar: bool = False,
    listo_para_enviar: bool = False,
    pendientes_revision: list[str] | None = None,
    es_cotizacion_adicional: bool = False,
    lead_categoria: str | None = None,
    lead_score: int | None = None,
    numero_publico: str = '',
    es_libre: bool = False,
    entrega_via: str = '',
    en_edicion: bool = False,
) -> dict[str, Any]:
    return {
        'tipo_entidad': tipo_entidad,
        'entidad_id': entidad_id,
        'origen': origen,
        'estado_normalizado': estado_normalizado,
        'estado_raw': estado_raw,
        'cliente_nombre': cliente_nombre,
        'cliente_telefono': cliente_telefono,
        'vehiculo_resumen': vehiculo_resumen,
        'servicio_resumen': servicio_resumen,
        'monto_clp': monto_clp,
        'fecha_referencia': fecha_referencia.isoformat() if fecha_referencia else None,
        'fecha_limite_respuesta': (
            fecha_limite_respuesta.isoformat() if fecha_limite_respuesta else None
        ),
        'tiempo_en_estado_horas': _tiempo_en_estado(fecha_referencia),
        'esperando_respuesta_24h': _esperando_respuesta_24h(
            fecha_referencia,
            estado_normalizado,
            lead_categoria,
        ),
        'conversation_id': conversation_id,
        'solicitud_id': solicitud_id,
        'oferta_id': oferta_id,
        'orden_id': orden_id,
        'cita_id': cita_id,
        'cotizacion_id': cotizacion_id,
        'miembro_taller_id': miembro_taller_id,
        'miembro_taller_nombre': miembro_taller_nombre,
        'template_generado_por_ia': template_generado_por_ia,
        'visto_sin_respuesta': visto_sin_respuesta,
        'demorado_48h': _demorado_48h(
            fecha_referencia,
            estado_normalizado,
            lead_categoria,
        ),
        'horario_por_confirmar': horario_por_confirmar,
        'listo_para_enviar': listo_para_enviar,
        'pendientes_revision': list(pendientes_revision or []),
        'es_cotizacion_adicional': es_cotizacion_adicional,
        'lead_categoria': lead_categoria or 'sin_calificar',
        'lead_score': lead_score if lead_score is not None else 0,
        'numero_publico': (numero_publico or '').strip(),
        'es_libre': bool(es_libre),
        'entrega_via': (entrega_via or '').strip(),
        'en_edicion': bool(en_edicion),
    }


def _template_generado_por_ia_desde_instancia(inst) -> bool:
    if inst is None or inst.checklist_template is None:
        return False
    tpl = inst.checklist_template
    return bool(tpl.generado_por_ia and tpl.revisado_en is None)


def _estado_normalizado_cita_personal(cita) -> str:
    if cita.estado == 'cancelada':
        return 'rechazado_perdido'
    if cita.estado == 'cerrada':
        return 'completado'
    if getattr(cita, 'horario_por_confirmar', False):
        return 'en_negociacion'

    inst = getattr(cita, 'checklist_instance', None)
    if inst is None:
        return CITA_PERSONAL_MAP.get(cita.estado, 'aceptado_agendado')
    if inst.estado in ('EN_PROGRESO', 'PAUSADO', 'PENDIENTE_FIRMA_CLIENTE'):
        return 'en_ejecucion'
    if inst.estado == 'COMPLETADO':
        return 'completado'
    return 'aceptado_agendado'


def _filas_ofertas(proveedor_user, taller: Taller | None) -> list[dict[str, Any]]:
    qs = (
        OfertaProveedor.objects.filter(proveedor=proveedor_user)
        .select_related('solicitud', 'solicitud__cliente', 'solicitud__vehiculo__marca', 'solicitud__vehiculo__modelo', 'miembro_taller_asignado')
        .order_by('-fecha_envio')[:200]
    )
    filas: list[dict[str, Any]] = []
    for oferta in qs:
        estado_norm = OFERTA_ESTADO_MAP.get(oferta.estado, 'nuevo')
        solicitud = oferta.solicitud
        cliente = solicitud.cliente if solicitud else None
        vehiculo = solicitud.vehiculo if solicitud else None
        vehiculo_txt = ''
        if vehiculo:
            marca = getattr(getattr(vehiculo, 'marca', None), 'nombre', '') or ''
            modelo = getattr(getattr(vehiculo, 'modelo', None), 'nombre', '') or ''
            vehiculo_txt = f'{marca} {modelo}'.strip()
        origen = 'catalogo' if oferta.origen == 'catalogo' else 'marketplace'
        fecha_ref = (
            oferta.fecha_visualizacion_cliente
            or oferta.fecha_envio
        )
        filas.append(
            _fila_base(
                tipo_entidad='oferta',
                entidad_id=str(oferta.id),
                origen=origen,
                estado_normalizado=estado_norm,
                estado_raw=oferta.estado,
                cliente_nombre=_contacto_nombre(
                    getattr(cliente, 'nombre', None),
                    getattr(cliente, 'apellido', None),
                ),
                cliente_telefono=getattr(cliente, 'telefono', '') or '',
                vehiculo_resumen=vehiculo_txt,
                servicio_resumen=(solicitud.descripcion_problema or '')[:120] if solicitud else '',
                monto_clp=_monto_a_float(oferta.precio_total_ofrecido),
                fecha_referencia=fecha_ref,
                solicitud_id=str(solicitud.id) if solicitud else None,
                oferta_id=str(oferta.id),
                miembro_taller_id=oferta.miembro_taller_asignado_id,
                miembro_taller_nombre=(
                    oferta.miembro_taller_asignado.nombre
                    if oferta.miembro_taller_asignado_id
                    else None
                ),
            )
        )
    return filas


def _vehiculo_resumen_cotizacion(cot: CotizacionCanal) -> str:
    """Patente · marca modelo · año — para Bandeja y detalle rápido."""
    partes: list[str] = []
    patente = (cot.vehiculo_patente or '').strip().upper()
    if patente:
        partes.append(patente)
    mm = ' '.join(p for p in [cot.vehiculo_marca, cot.vehiculo_modelo] if p).strip()
    if mm:
        partes.append(mm)
    if cot.vehiculo_anio:
        partes.append(str(cot.vehiculo_anio))
    return ' · '.join(partes)


def _estado_normalizado_cotizacion_canal(cot: CotizacionCanal) -> str:
    """
    Aceptada solo es «negociando» si aún hay cita activa por confirmar/agendar.
    Si la cita se canceló o eliminó, el lead va a Perdidos (no queda zombie Agendado).
    """
    if cot.estado == 'aceptada':
        from mecanimovilapp.apps.ordenes.services.cita_cotizacion_sync import (
            cotizacion_aceptada_tiene_cita_activa,
        )
        if not cotizacion_aceptada_tiene_cita_activa(cot):
            return 'rechazado_perdido'
        return 'en_negociacion'
    return COTIZACION_CANAL_MAP.get(cot.estado, 'nuevo')


def _hay_folio_publico(cot: CotizacionCanal) -> bool:
    return bool((cot.numero_publico or '').strip())


def _entrega_via_cotizacion(cot: CotizacionCanal) -> str:
    meta = cot.metadata if isinstance(cot.metadata, dict) else {}
    return str(meta.get('entrega_canal') or '').strip()


def _es_borrador_en_edicion(cot: CotizacionCanal) -> bool:
    if cot.estado != 'borrador':
        return False
    meta = cot.metadata if isinstance(cot.metadata, dict) else {}
    return _hay_folio_publico(cot) or bool(meta.get('reabierta_por_taller'))


def _normalizar_busqueda(q: str | None) -> str:
    return ' '.join((q or '').strip().lower().split())


def _digitos_busqueda(q: str) -> str:
    return ''.join(c for c in q if c.isdigit())


def _filtrar_cotizaciones_queryset(qs, q: str):
    """Filtra CotizacionCanal por folio MM, id, cliente, vehículo o servicio."""
    needle = _normalizar_busqueda(q)
    if not needle:
        return qs
    filtros = (
        Q(numero_publico__icontains=needle)
        | Q(cliente_nombre__icontains=needle)
        | Q(cliente_telefono__icontains=needle)
        | Q(vehiculo_marca__icontains=needle)
        | Q(vehiculo_modelo__icontains=needle)
        | Q(vehiculo_patente__icontains=needle)
        | Q(servicio_nombre__icontains=needle)
        | Q(descripcion_problema__icontains=needle)
    )
    folio = needle.upper().replace(' ', '')
    if folio.startswith('MM-') or folio.startswith('MM'):
        filtros |= Q(numero_publico__iexact=folio if folio.startswith('MM-') else f'MM-{folio[2:].zfill(6)}')
        filtros |= Q(numero_publico__icontains=folio)
    digits = _digitos_busqueda(needle)
    if digits:
        filtros |= Q(numero_publico__icontains=digits)
        filtros |= Q(numero_publico__iendswith=digits.zfill(6))
        try:
            filtros |= Q(pk=int(digits))
        except (TypeError, ValueError):
            pass
    return qs.filter(filtros)


def _fila_coincide_busqueda(fila: dict[str, Any], q: str) -> bool:
    needle = _normalizar_busqueda(q)
    if not needle:
        return True
    haystack = ' '.join(
        str(fila.get(k) or '')
        for k in (
            'numero_publico',
            'cliente_nombre',
            'cliente_telefono',
            'vehiculo_resumen',
            'servicio_resumen',
            'cotizacion_id',
            'entidad_id',
        )
    ).lower()
    if needle in haystack:
        return True
    compact = needle.replace(' ', '').replace('-', '')
    folio = str(fila.get('numero_publico') or '').lower().replace('-', '')
    if compact and compact in folio:
        return True
    digits = _digitos_busqueda(needle)
    if digits and digits in ''.join(c for c in haystack if c.isdigit()):
        return True
    return False


def _lead_fields(conversation_id: int | None, leads_map: dict) -> dict[str, Any]:
    if not conversation_id:
        return {'lead_categoria': 'sin_calificar', 'lead_score': 0}
    lead = leads_map.get(conversation_id)
    if lead is None:
        return {'lead_categoria': 'sin_calificar', 'lead_score': 0}
    return {
        'lead_categoria': lead.categoria,
        'lead_score': lead.score,
    }


def _filas_cotizaciones_canal(
    taller: Taller,
    leads_map: dict | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    qs = (
        CotizacionCanal.objects.filter(taller=taller)
        .filter(
            ~Q(estado='borrador')
            | (
                ~Q(numero_publico='')
                & Q(numero_publico__isnull=False)
            )
            | Q(metadata__reabierta_por_taller=True)
        )
        .select_related(
            'conversation',
            'conversation__external_contact',
            'cita_origen',
            'cotizacion_original',
        )
        .order_by('-actualizado_en')
    )
    needle = _normalizar_busqueda(q)
    if needle:
        qs = _filtrar_cotizaciones_queryset(qs, needle)[:1000]
    else:
        qs = qs[:500]
    filas: list[dict[str, Any]] = []
    leads_map = leads_map or {}
    for cot in qs:
        if cot.estado == 'borrador' and not _es_borrador_en_edicion(cot) and not _hay_folio_publico(cot):
            continue
        estado_norm = _estado_normalizado_cotizacion_canal(cot)
        conv = cot.conversation
        ext = getattr(conv, 'external_contact', None) if conv else None
        if cot.es_libre:
            cliente_nombre = cot.cliente_nombre or 'Cliente'
            cliente_telefono = cot.cliente_telefono or ''
            origen = 'directo'
        else:
            cliente_nombre = (
                (cot.cliente_nombre or '').strip()
                or getattr(ext, 'display_name', None)
                or cot.vehiculo_marca
                or 'Contacto'
            )
            cliente_telefono = (
                (cot.cliente_telefono or '').strip()
                or getattr(ext, 'phone', '')
                or ''
            )
            origen = _canal_origen(conv)
        fecha_ref = cot.enviada_en or cot.actualizado_en or cot.creado_en
        vehiculo_txt = _vehiculo_resumen_cotizacion(cot)
        en_edicion = _es_borrador_en_edicion(cot)
        filas.append(
            _fila_base(
                tipo_entidad='cotizacion_canal',
                entidad_id=str(cot.id),
                origen=origen,
                estado_normalizado=estado_norm,
                estado_raw=cot.estado,
                cliente_nombre=str(cliente_nombre),
                cliente_telefono=cliente_telefono,
                vehiculo_resumen=vehiculo_txt,
                servicio_resumen=(cot.servicio_nombre or cot.descripcion_problema or '')[:120],
                monto_clp=_monto_a_float(cot.total_clp),
                fecha_referencia=fecha_ref,
                conversation_id=conv.id if conv else None,
                cotizacion_id=cot.id,
                cita_id=getattr(cot, 'cita_origen_id', None),
                visto_sin_respuesta=_visto_sin_respuesta(estado_norm, cot.visto_en),
                es_cotizacion_adicional=bool(getattr(cot, 'es_cotizacion_adicional', False)),
                numero_publico=(cot.numero_publico or '').strip(),
                es_libre=bool(cot.es_libre),
                entrega_via=_entrega_via_cotizacion(cot),
                en_edicion=en_edicion,
                **_lead_fields(conv.id if conv else None, leads_map),
            )
        )
    return filas


def _filas_cotizaciones_borrador_agente(taller: Taller, leads_map: dict | None = None) -> list[dict[str, Any]]:
    """Borradores del agente IA pendientes de revisión/envío por el taller."""
    qs = (
        CotizacionCanal.objects.filter(
            taller=taller,
            estado='borrador',
            metadata__origen='agente_ia',
        )
        .select_related('conversation', 'conversation__external_contact')
        .order_by('-actualizado_en')[:50]
    )
    filas: list[dict[str, Any]] = []
    leads_map = leads_map or {}
    for cot in qs:
        meta = cot.metadata if isinstance(cot.metadata, dict) else {}
        conv = cot.conversation
        ext = getattr(conv, 'external_contact', None) if conv else None
        cliente_nombre = (
            (cot.cliente_nombre or '').strip()
            or getattr(ext, 'display_name', None)
            or 'Contacto'
        )
        cliente_telefono = (cot.cliente_telefono or '').strip() or getattr(ext, 'phone', '') or ''
        origen = _canal_origen(conv) if conv else 'canal'
        vehiculo_txt = _vehiculo_resumen_cotizacion(cot)
        fecha_ref = cot.actualizado_en or cot.creado_en
        filas.append(
            _fila_base(
                tipo_entidad='cotizacion_canal',
                entidad_id=str(cot.id),
                origen=origen,
                estado_normalizado='nuevo',
                estado_raw='borrador',
                cliente_nombre=str(cliente_nombre),
                cliente_telefono=cliente_telefono,
                vehiculo_resumen=vehiculo_txt,
                servicio_resumen=(cot.servicio_nombre or cot.descripcion_problema or '')[:120],
                monto_clp=_monto_a_float(cot.total_clp),
                fecha_referencia=fecha_ref,
                conversation_id=conv.id if conv else None,
                cotizacion_id=cot.id,
                listo_para_enviar=bool(meta.get('listo_para_enviar')),
                pendientes_revision=list(meta.get('pendientes_revision') or []),
                numero_publico=(cot.numero_publico or '').strip(),
                es_libre=bool(cot.es_libre),
                entrega_via=_entrega_via_cotizacion(cot),
                en_edicion=_es_borrador_en_edicion(cot),
                **_lead_fields(conv.id if conv else None, leads_map),
            )
        )
    return filas


def _filas_citas_personales(
    taller: Taller,
    miembro_id: int | None = None,
    leads_map: dict | None = None,
) -> list[dict[str, Any]]:
    qs = (
        CitaAgendaPersonal.objects.filter(taller=taller)
        .select_related(
            'detalle',
            'miembro_taller',
            'checklist_instance__checklist_template',
            'cotizacion_canal_origen',
            'conversation_origen',
        )
        .order_by('-fecha_servicio', '-hora_servicio')[:200]
    )
    if miembro_id:
        qs = qs.filter(miembro_taller_id=miembro_id)
    filas: list[dict[str, Any]] = []
    leads_map = leads_map or {}
    for cita in qs:
        det = cita.detalle
        estado_norm = _estado_normalizado_cita_personal(cita)
        inst = getattr(cita, 'checklist_instance', None)
        vehiculo_txt = ' '.join(
            p for p in [det.vehiculo_marca, det.vehiculo_modelo] if p
        ).strip()
        cot_origen = getattr(cita, 'cotizacion_canal_origen', None)
        if cot_origen is not None and getattr(cot_origen, 'es_libre', False):
            origen_cita = 'directo'
        elif cita.conversation_origen_id:
            origen_cita = _canal_origen(cita.conversation_origen)
        else:
            origen_cita = 'manual'
        filas.append(
            _fila_base(
                tipo_entidad='cita_personal',
                entidad_id=str(cita.id),
                origen=origen_cita,
                estado_normalizado=estado_norm,
                estado_raw=cita.estado,
                cliente_nombre=det.cliente_nombre or 'Cliente',
                cliente_telefono=det.cliente_telefono or '',
                vehiculo_resumen=vehiculo_txt,
                servicio_resumen=(det.descripcion or det.servicio_nombre or '')[:120],
                monto_clp=_monto_a_float(
                    cot_origen.total_clp if cot_origen is not None else det.precio_referencia
                ),
                fecha_referencia=cita.fecha_creacion,
                cita_id=cita.id,
                conversation_id=cita.conversation_origen_id,
                cotizacion_id=cot_origen.id if cot_origen is not None else None,
                miembro_taller_id=cita.miembro_taller_id,
                miembro_taller_nombre=(
                    cita.miembro_taller.nombre if cita.miembro_taller_id else None
                ),
                template_generado_por_ia=_template_generado_por_ia_desde_instancia(inst),
                horario_por_confirmar=bool(getattr(cita, 'horario_por_confirmar', False)),
                **_lead_fields(cita.conversation_origen_id, leads_map),
            )
        )
    return filas


def _filas_solicitudes_publicas_sin_oferta(proveedor_user, taller: Taller | None) -> list[dict[str, Any]]:
    """Solicitudes marketplace disponibles para cotizar (sin oferta activa del proveedor)."""
    if taller is None:
        return []

    marcas_atendidas = list(taller.marcas_atendidas.values_list('id', flat=True))

    solicitudes_globales = SolicitudServicioPublica.objects.filter(
        estado__in=['publicada', 'con_ofertas'],
        fecha_expiracion__gt=timezone.now(),
        tipo_solicitud='global',
    )
    if marcas_atendidas:
        solicitudes_globales = solicitudes_globales.filter(vehiculo__marca__id__in=marcas_atendidas)
    else:
        solicitudes_globales = solicitudes_globales.none()

    solicitudes_dirigidas = SolicitudServicioPublica.objects.filter(
        proveedores_dirigidos=proveedor_user,
        estado__in=['publicada', 'con_ofertas', 'pendiente_confirmacion'],
        fecha_expiracion__gt=timezone.now(),
        tipo_solicitud='dirigida',
    )

    queryset = solicitudes_globales | solicitudes_dirigidas

    ofertas_proveedor = OfertaProveedor.objects.filter(
        proveedor=proveedor_user,
        estado__in=['enviada', 'vista', 'en_chat', 'aceptada', 'expirada'],
    ).values_list('solicitud_id', flat=True)
    if ofertas_proveedor:
        queryset = queryset.exclude(id__in=ofertas_proveedor)

    rechazos_proveedor = RechazoSolicitud.objects.filter(
        proveedor=proveedor_user,
    ).values_list('solicitud_id', flat=True)
    if rechazos_proveedor:
        queryset = queryset.exclude(id__in=rechazos_proveedor)

    qs = (
        queryset.distinct()
        .select_related('cliente', 'vehiculo__marca', 'vehiculo__modelo')
        .order_by('-fecha_publicacion', '-fecha_creacion')[:100]
    )

    filas: list[dict[str, Any]] = []
    for solicitud in qs:
        estado_norm = SOLICITUD_PUBLICA_MAP.get(solicitud.estado, 'nuevo')
        cliente = solicitud.cliente
        vehiculo = solicitud.vehiculo
        vehiculo_txt = ''
        if vehiculo:
            marca = getattr(getattr(vehiculo, 'marca', None), 'nombre', '') or ''
            modelo = getattr(getattr(vehiculo, 'modelo', None), 'nombre', '') or ''
            vehiculo_txt = f'{marca} {modelo}'.strip()
        fecha_ref = solicitud.fecha_publicacion or solicitud.fecha_creacion
        filas.append(
            _fila_base(
                tipo_entidad='solicitud_publica',
                entidad_id=str(solicitud.id),
                origen='marketplace',
                estado_normalizado=estado_norm if estado_norm != 'cotizacion_enviada' else 'nuevo',
                estado_raw=solicitud.estado,
                cliente_nombre=_contacto_nombre(
                    getattr(cliente, 'nombre', None),
                    getattr(cliente, 'apellido', None),
                ),
                cliente_telefono=getattr(cliente, 'telefono', '') or '',
                vehiculo_resumen=vehiculo_txt,
                servicio_resumen=(solicitud.descripcion_problema or '')[:120],
                monto_clp=None,
                fecha_referencia=fecha_ref,
                fecha_limite_respuesta=solicitud.fecha_expiracion,
                solicitud_id=str(solicitud.id),
            )
        )
    return filas


def _filas_solicitudes_directas(taller: Taller, proveedor_user) -> list[dict[str, Any]]:
    qs = (
        SolicitudServicio.objects.filter(taller=taller)
        .select_related('cliente', 'vehiculo__marca', 'vehiculo__modelo', 'mecanico_asignado')
        .order_by('-fecha_hora_solicitud')[:100]
    )
    filas: list[dict[str, Any]] = []
    for orden in qs:
        estado_norm = SOLICITUD_DIRECTA_MAP.get(orden.estado, 'nuevo')
        cliente = orden.cliente
        vehiculo = orden.vehiculo
        vehiculo_txt = ''
        if vehiculo:
            marca = getattr(getattr(vehiculo, 'marca', None), 'nombre', '') or ''
            modelo = getattr(getattr(vehiculo, 'modelo', None), 'nombre', '') or ''
            vehiculo_txt = f'{marca} {modelo}'.strip()
        filas.append(
            _fila_base(
                tipo_entidad='orden_directa',
                entidad_id=str(orden.id),
                origen='marketplace',
                estado_normalizado=estado_norm,
                estado_raw=orden.estado,
                cliente_nombre=_contacto_nombre(
                    getattr(cliente, 'nombre', None),
                    getattr(cliente, 'apellido', None),
                ),
                cliente_telefono=getattr(cliente, 'telefono', '') or '',
                vehiculo_resumen=vehiculo_txt,
                servicio_resumen=(orden.notas_cliente or '')[:120],
                monto_clp=_monto_a_float(orden.total),
                fecha_referencia=orden.fecha_hora_solicitud,
                orden_id=orden.id,
                miembro_taller_id=orden.mecanico_asignado_id,
                miembro_taller_nombre=(
                    orden.mecanico_asignado.nombre if orden.mecanico_asignado_id else None
                ),
            )
        )
    return filas


_DEDUPE_TIPO_PRIORITY = {
    # Si hay cita y cotización del mismo caso, la cita manda el estado real.
    'cita_personal': 0,
    'orden_directa': 1,
    'oferta': 2,
    'cotizacion_canal': 3,
    'solicitud_publica': 4,
}


def _pipeline_dedupe_key(fila: dict[str, Any]) -> str:
    # Una fila por folio de cotización: no colapsar el caso en el chat ni en la cita.
    if fila.get('tipo_entidad') == 'cotizacion_canal' and fila.get('cotizacion_id'):
        return f'cot:{fila["cotizacion_id"]}'
    if fila.get('es_cotizacion_adicional') and fila.get('cotizacion_id'):
        return f'cot_adicional:{fila["cotizacion_id"]}'
    conv_id = fila.get('conversation_id')
    if conv_id:
        return f'conv:{conv_id}'
    if fila.get('cotizacion_id'):
        return f'cot:{fila["cotizacion_id"]}'
    if fila.get('oferta_id'):
        return f'oferta:{fila["oferta_id"]}'
    if fila.get('solicitud_id'):
        return f'sol:{fila["solicitud_id"]}'
    if fila.get('cita_id'):
        return f'cita:{fila["cita_id"]}'
    if fila.get('orden_id'):
        return f'orden:{fila["orden_id"]}'
    return f'{fila.get("tipo_entidad")}:{fila.get("entidad_id")}'


def _dedupe_pipeline_filas(filas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Colapsa filas repetidas del mismo hilo comercial, excepto cotizaciones de canal:
    cada CotizacionCanal es un caso con folio MM propio.
    """
    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for fila in filas:
        key = _pipeline_dedupe_key(fila)
        prev = best.get(key)
        if prev is None:
            best[key] = fila
            order.append(key)
            continue
        p_new = _DEDUPE_TIPO_PRIORITY.get(str(fila.get('tipo_entidad')), 9)
        p_old = _DEDUPE_TIPO_PRIORITY.get(str(prev.get('tipo_entidad')), 9)
        if p_new < p_old:
            best[key] = fila
        elif p_new == p_old:
            if (fila.get('fecha_referencia') or '') > (prev.get('fecha_referencia') or ''):
                best[key] = fila
    return [best[k] for k in order]


def construir_pipeline_comercial(
    *,
    user,
    taller: Taller | None,
    estado_normalizado: str | None = None,
    origen: str | None = None,
    solo_esperando_24h: bool = False,
    miembro_taller_id: int | None = None,
    limite: int = 100,
    incluir_borradores: bool = False,
    q: str | None = None,
) -> dict[str, Any]:
    """Construye la lista agregada del pipeline comercial del proveedor."""
    if taller is None:
        return {'count': 0, 'results': [], 'resumen': {}, 'borradores_pendientes_count': 0}

    from mecanimovilapp.apps.agente_ia.models import LeadCalificacion

    leads_map = {
        lc.conversation_id: lc
        for lc in LeadCalificacion.objects.filter(taller=taller)
    }

    filas: list[dict[str, Any]] = []
    filas.extend(_filas_solicitudes_publicas_sin_oferta(user, taller))
    filas.extend(_filas_ofertas(user, taller))
    if incluir_borradores:
        filas.extend(_filas_cotizaciones_borrador_agente(taller, leads_map))
    filas.extend(_filas_cotizaciones_canal(taller, leads_map, q=q))
    filas.extend(_filas_citas_personales(taller, miembro_taller_id, leads_map))
    filas.extend(_filas_solicitudes_directas(taller, user))

    borradores_pendientes_count = CotizacionCanal.objects.filter(
        taller=taller,
        estado='borrador',
    ).count()

    if estado_normalizado:
        filas = [f for f in filas if f['estado_normalizado'] == estado_normalizado]
    if origen:
        filas = [f for f in filas if f['origen'] == origen]
    if solo_esperando_24h:
        filas = [f for f in filas if f['esperando_respuesta_24h']]
    if miembro_taller_id:
        filas = [
            f for f in filas
            if f.get('miembro_taller_id') in (None, miembro_taller_id)
        ]
    if q:
        filas = [f for f in filas if _fila_coincide_busqueda(f, q)]

    filas.sort(
        key=lambda f: (
            bool(f.get('listo_para_enviar')),
            int(f.get('lead_score') or 0),
            f.get('fecha_referencia') or '',
        ),
        reverse=True,
    )
    filas = _dedupe_pipeline_filas(filas)
    filas = filas[:limite]

    resumen: dict[str, int] = {k: 0 for k in ESTADOS_NORMALIZADOS}
    for f in filas:
        key = f.get('estado_normalizado')
        if key in resumen:
            resumen[key] += 1

    return {
        'count': len(filas),
        'results': filas,
        'resumen': resumen,
        'esperando_respuesta_24h_count': sum(
            1 for f in filas if f.get('esperando_respuesta_24h')
        ),
        'borradores_pendientes_count': borradores_pendientes_count,
    }
