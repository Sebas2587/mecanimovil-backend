"""
Agregador de pipeline comercial unificado para proveedores.
Normaliza solicitudes, ofertas, cotizaciones de canal y citas personales.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Q, Value
from django.db.models.functions import Replace, Upper
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


def _vehiculo_resumen_partes(
    patente: str = '',
    marca: str = '',
    modelo: str = '',
    anio=None,
) -> str:
    """Patente · marca modelo · año — para Bandeja y detalle rápido."""
    partes: list[str] = []
    patente_txt = (patente or '').strip().upper()
    if patente_txt:
        partes.append(patente_txt)
    mm = ' '.join(p for p in [marca, modelo] if p).strip()
    if mm:
        partes.append(mm)
    if anio:
        partes.append(str(anio))
    return ' · '.join(partes)


def _campos_vehiculo_obj(vehiculo) -> dict[str, Any]:
    if vehiculo is None:
        return {
            'vehiculo_patente': '',
            'vehiculo_marca': '',
            'vehiculo_modelo': '',
            'vehiculo_anio': None,
        }
    marca = getattr(getattr(vehiculo, 'marca', None), 'nombre', '') or ''
    modelo = getattr(getattr(vehiculo, 'modelo', None), 'nombre', '') or ''
    patente = (getattr(vehiculo, 'patente', None) or '').strip().upper()
    anio = getattr(vehiculo, 'year', None)
    return {
        'vehiculo_patente': patente,
        'vehiculo_marca': marca,
        'vehiculo_modelo': modelo,
        'vehiculo_anio': anio,
    }


def _cliente_user_id(cliente) -> int | None:
    if cliente is None:
        return None
    uid = getattr(cliente, 'usuario_id', None)
    if uid:
        return int(uid)
    if hasattr(cliente, 'username') and getattr(cliente, 'id', None):
        return int(cliente.id)
    cid = getattr(cliente, 'id', None)
    return int(cid) if cid else None


def _telefono_contacto_ext(ext) -> str:
    if ext is None:
        return ''
    fn = getattr(ext, 'telefono_efectivo', None)
    if callable(fn):
        return (fn() or '').strip()
    return (getattr(ext, 'phone', None) or '').strip()


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
    vehiculo_patente: str = '',
    vehiculo_marca: str = '',
    vehiculo_modelo: str = '',
    vehiculo_anio: int | None = None,
    cliente_user_id: int | None = None,
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
    patente = (vehiculo_patente or '').strip().upper()
    resumen = vehiculo_resumen or _vehiculo_resumen_partes(
        patente, vehiculo_marca, vehiculo_modelo, vehiculo_anio
    )
    return {
        'tipo_entidad': tipo_entidad,
        'entidad_id': entidad_id,
        'origen': origen,
        'estado_normalizado': estado_normalizado,
        'estado_raw': estado_raw,
        'cliente_nombre': cliente_nombre,
        'cliente_telefono': cliente_telefono,
        'vehiculo_resumen': resumen,
        'vehiculo_patente': patente,
        'vehiculo_marca': (vehiculo_marca or '').strip(),
        'vehiculo_modelo': (vehiculo_modelo or '').strip(),
        'vehiculo_anio': vehiculo_anio,
        'cliente_user_id': cliente_user_id,
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
        veh = _campos_vehiculo_obj(solicitud.vehiculo if solicitud else None)
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
                cliente_user_id=_cliente_user_id(cliente),
                vehiculo_resumen=_vehiculo_resumen_partes(
                    veh['vehiculo_patente'],
                    veh['vehiculo_marca'],
                    veh['vehiculo_modelo'],
                    veh['vehiculo_anio'],
                ),
                vehiculo_patente=veh['vehiculo_patente'],
                vehiculo_marca=veh['vehiculo_marca'],
                vehiculo_modelo=veh['vehiculo_modelo'],
                vehiculo_anio=veh['vehiculo_anio'],
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
    return _vehiculo_resumen_partes(
        cot.vehiculo_patente or '',
        cot.vehiculo_marca or '',
        cot.vehiculo_modelo or '',
        cot.vehiculo_anio,
    )


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


def _compactar_alfanum(q: str | None) -> str:
    return ''.join(c for c in (q or '').lower() if c.isalnum())


def _digitos_busqueda(q: str) -> str:
    return ''.join(c for c in q if c.isdigit())


def _es_consulta_numerica(q: str) -> bool:
    compact = _compactar_alfanum(q)
    return bool(compact) and compact.isdigit()


def _patente_compact_expr(field: str):
    expr = Upper(field)
    for ch in ('-', ' ', '.'):
        expr = Replace(expr, Value(ch), Value(''))
    return expr


def _filtrar_cotizaciones_queryset(qs, q: str):
    """Filtra CotizacionCanal por folio MM, id, cliente, vehículo o servicio."""
    needle = _normalizar_busqueda(q)
    if not needle:
        return qs
    compact = _compactar_alfanum(needle).upper()
    qs = qs.annotate(_patente_compact=_patente_compact_expr('vehiculo_patente'))
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
    if compact:
        filtros |= Q(_patente_compact__contains=compact)
    folio = needle.upper().replace(' ', '')
    if folio.startswith('MM-') or folio.startswith('MM'):
        filtros |= Q(numero_publico__iexact=folio if folio.startswith('MM-') else f'MM-{folio[2:].zfill(6)}')
        filtros |= Q(numero_publico__icontains=folio)
    digits = _digitos_busqueda(needle)
    if digits and _es_consulta_numerica(needle):
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
            'vehiculo_patente',
            'servicio_resumen',
            'cotizacion_id',
            'entidad_id',
        )
    ).lower()
    if needle in haystack:
        return True
    compact = _compactar_alfanum(needle)
    hay_c = _compactar_alfanum(haystack)
    if compact and compact in hay_c:
        return True
    if _es_consulta_numerica(needle):
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
        .prefetch_related('citas_generadas')
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
                or _telefono_contacto_ext(ext)
            )
            origen = _canal_origen(conv)
        fecha_ref = cot.enviada_en or cot.actualizado_en or cot.creado_en
        en_edicion = _es_borrador_en_edicion(cot)
        cita_rel = _cita_activa_de_cotizacion(cot)
        cita_id = getattr(cot, 'cita_origen_id', None) or (cita_rel.id if cita_rel else None)
        filas.append(
            _fila_base(
                tipo_entidad='cotizacion_canal',
                entidad_id=str(cot.id),
                origen=origen,
                estado_normalizado=estado_norm,
                estado_raw=cot.estado,
                cliente_nombre=str(cliente_nombre),
                cliente_telefono=cliente_telefono,
                vehiculo_resumen=_vehiculo_resumen_cotizacion(cot),
                vehiculo_patente=cot.vehiculo_patente or '',
                vehiculo_marca=cot.vehiculo_marca or '',
                vehiculo_modelo=cot.vehiculo_modelo or '',
                vehiculo_anio=cot.vehiculo_anio,
                servicio_resumen=(cot.servicio_nombre or cot.descripcion_problema or '')[:120],
                monto_clp=_monto_a_float(cot.total_clp),
                fecha_referencia=fecha_ref,
                conversation_id=conv.id if conv else None,
                cotizacion_id=cot.id,
                cita_id=cita_id,
                horario_por_confirmar=bool(
                    cita_rel and getattr(cita_rel, 'horario_por_confirmar', False)
                ),
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
        cliente_telefono = (cot.cliente_telefono or '').strip() or _telefono_contacto_ext(ext)
        origen = _canal_origen(conv) if conv else 'canal'
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
                vehiculo_resumen=_vehiculo_resumen_cotizacion(cot),
                vehiculo_patente=cot.vehiculo_patente or '',
                vehiculo_marca=cot.vehiculo_marca or '',
                vehiculo_modelo=cot.vehiculo_modelo or '',
                vehiculo_anio=cot.vehiculo_anio,
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
    q: str | None = None,
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
        .order_by('-fecha_servicio', '-hora_servicio')
    )
    if miembro_id:
        qs = qs.filter(miembro_taller_id=miembro_id)
    needle = _normalizar_busqueda(q)
    if needle:
        compact = _compactar_alfanum(needle).upper()
        qs = qs.annotate(_patente_compact=_patente_compact_expr('detalle__vehiculo_patente'))
        filtros = (
            Q(detalle__cliente_nombre__icontains=needle)
            | Q(detalle__cliente_telefono__icontains=needle)
            | Q(detalle__vehiculo_marca__icontains=needle)
            | Q(detalle__vehiculo_modelo__icontains=needle)
            | Q(detalle__vehiculo_patente__icontains=needle)
            | Q(detalle__servicio_nombre__icontains=needle)
            | Q(detalle__descripcion__icontains=needle)
            | Q(cotizacion_canal_origen__numero_publico__icontains=needle)
        )
        if compact:
            filtros |= Q(_patente_compact__contains=compact)
        qs = qs.filter(filtros)[:400]
    else:
        qs = qs[:200]
    filas: list[dict[str, Any]] = []
    leads_map = leads_map or {}
    for cita in qs:
        det = cita.detalle
        if det is None:
            continue
        estado_norm = _estado_normalizado_cita_personal(cita)
        inst = getattr(cita, 'checklist_instance', None)
        patente = getattr(det, 'vehiculo_patente', '') or ''
        marca = det.vehiculo_marca or ''
        modelo = det.vehiculo_modelo or ''
        anio = getattr(det, 'vehiculo_anio', None)
        vehiculo_txt = _vehiculo_resumen_partes(patente, marca, modelo, anio)
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
                vehiculo_patente=patente,
                vehiculo_marca=marca,
                vehiculo_modelo=modelo,
                vehiculo_anio=anio,
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
        veh = _campos_vehiculo_obj(solicitud.vehiculo)
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
                cliente_user_id=_cliente_user_id(cliente),
                vehiculo_resumen=_vehiculo_resumen_partes(
                    veh['vehiculo_patente'],
                    veh['vehiculo_marca'],
                    veh['vehiculo_modelo'],
                    veh['vehiculo_anio'],
                ),
                vehiculo_patente=veh['vehiculo_patente'],
                vehiculo_marca=veh['vehiculo_marca'],
                vehiculo_modelo=veh['vehiculo_modelo'],
                vehiculo_anio=veh['vehiculo_anio'],
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
        veh = _campos_vehiculo_obj(orden.vehiculo)
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
                cliente_user_id=_cliente_user_id(cliente),
                vehiculo_resumen=_vehiculo_resumen_partes(
                    veh['vehiculo_patente'],
                    veh['vehiculo_marca'],
                    veh['vehiculo_modelo'],
                    veh['vehiculo_anio'],
                ),
                vehiculo_patente=veh['vehiculo_patente'],
                vehiculo_marca=veh['vehiculo_marca'],
                vehiculo_modelo=veh['vehiculo_modelo'],
                vehiculo_anio=veh['vehiculo_anio'],
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
    'cita_personal': 0,
    'orden_directa': 1,
    'oferta': 2,
    'cotizacion_canal': 3,
    'solicitud_publica': 4,
}

_ESTADO_RANK = {
    'rechazado_perdido': 0,
    'nuevo': 1,
    'cotizacion_enviada': 2,
    'en_negociacion': 3,
    'aceptado_agendado': 4,
    'en_ejecucion': 5,
    'completado': 6,
}


def _cita_activa_de_cotizacion(cot: CotizacionCanal):
    citas = list(getattr(cot, 'citas_generadas', []).all()) if hasattr(cot, 'citas_generadas') else []
    activas = [c for c in citas if getattr(c, 'estado', None) == 'activa']
    if not activas:
        return None
    por_confirmar = [c for c in activas if getattr(c, 'horario_por_confirmar', False)]
    return (por_confirmar or activas)[0]


def _pipeline_dedupe_key(fila: dict[str, Any]) -> str:
    # Un caso = un folio. Cita ligada a esa cotización comparte la misma clave.
    if fila.get('es_cotizacion_adicional') and fila.get('cotizacion_id'):
        return f'cot_adicional:{fila["cotizacion_id"]}'
    if fila.get('cotizacion_id'):
        return f'cot:{fila["cotizacion_id"]}'
    conv_id = fila.get('conversation_id')
    if conv_id:
        return f'conv:{conv_id}'
    if fila.get('oferta_id'):
        return f'oferta:{fila["oferta_id"]}'
    if fila.get('solicitud_id'):
        return f'sol:{fila["solicitud_id"]}'
    if fila.get('cita_id'):
        return f'cita:{fila["cita_id"]}'
    if fila.get('orden_id'):
        return f'orden:{fila["orden_id"]}'
    return f'{fila.get("tipo_entidad")}:{fila.get("entidad_id")}'


def _fusionar_filas_mismo_caso(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """La cotización (folio MM) es la fila visible; absorbe cita_id y horario."""
    cot = a if a.get('tipo_entidad') == 'cotizacion_canal' else (
        b if b.get('tipo_entidad') == 'cotizacion_canal' else None
    )
    cita = a if a.get('tipo_entidad') == 'cita_personal' else (
        b if b.get('tipo_entidad') == 'cita_personal' else None
    )
    if cot is not None and cita is not None:
        merged = dict(cot)
        merged['cita_id'] = cita.get('cita_id') or cot.get('cita_id')
        merged['horario_por_confirmar'] = bool(
            cita.get('horario_por_confirmar') or cot.get('horario_por_confirmar')
        )
        if cita.get('miembro_taller_id') and not merged.get('miembro_taller_id'):
            merged['miembro_taller_id'] = cita['miembro_taller_id']
            merged['miembro_taller_nombre'] = cita.get('miembro_taller_nombre')
        if cita.get('template_generado_por_ia'):
            merged['template_generado_por_ia'] = True
        rank_cot = _ESTADO_RANK.get(str(cot.get('estado_normalizado')), 0)
        rank_cita = _ESTADO_RANK.get(str(cita.get('estado_normalizado')), 0)
        if cot.get('estado_raw') == 'borrador' or cot.get('en_edicion'):
            merged['en_edicion'] = True
            merged['estado_raw'] = 'borrador'
            merged['estado_normalizado'] = cot.get('estado_normalizado') or 'nuevo'
        else:
            merged['en_edicion'] = False
            if rank_cita > rank_cot:
                merged['estado_normalizado'] = cita['estado_normalizado']
                merged['estado_raw'] = cita.get('estado_raw') or merged.get('estado_raw')
        return merged
    p_a = _DEDUPE_TIPO_PRIORITY.get(str(a.get('tipo_entidad')), 9)
    p_b = _DEDUPE_TIPO_PRIORITY.get(str(b.get('tipo_entidad')), 9)
    if p_b < p_a:
        return b
    if p_a == p_b and (b.get('fecha_referencia') or '') > (a.get('fecha_referencia') or ''):
        return b
    return a


def _dedupe_pipeline_filas(filas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Una fila por caso: dos cotizaciones del mismo chat siguen siendo dos filas;
    la cita de esa cotización se fusiona en el folio MM (no duplica al cliente).
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
        best[key] = _fusionar_filas_mismo_caso(prev, fila)
    return [best[k] for k in order]


def _recoger_filas_pipeline(
    *,
    user,
    taller: Taller,
    incluir_borradores: bool = False,
    q: str | None = None,
    miembro_taller_id: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
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
    filas.extend(_filas_citas_personales(taller, miembro_taller_id, leads_map, q=q))
    filas.extend(_filas_solicitudes_directas(taller, user))
    borradores_pendientes_count = CotizacionCanal.objects.filter(
        taller=taller,
        estado='borrador',
    ).count()
    return filas, borradores_pendientes_count


def _ordenar_filas_recientes(filas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filas.sort(
        key=lambda f: (
            f.get('fecha_referencia') or '',
            bool(f.get('listo_para_enviar')),
            int(f.get('lead_score') or 0),
        ),
        reverse=True,
    )
    return filas


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

    filas, borradores_pendientes_count = _recoger_filas_pipeline(
        user=user,
        taller=taller,
        incluir_borradores=incluir_borradores,
        q=q,
        miembro_taller_id=miembro_taller_id,
    )

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

    # Más reciente primero (fecha_referencia ISO desc). listo_para_enviar y lead_score
    # solo desempatan filas con la misma fecha.
    filas = _ordenar_filas_recientes(filas)
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


_NOMBRES_GENERICOS = frozenset({'cliente', 'contacto', ''})

_CASO_PUBLICO_KEYS = (
    'tipo_entidad',
    'entidad_id',
    'numero_publico',
    'servicio_resumen',
    'monto_clp',
    'estado_normalizado',
    'estado_raw',
    'origen',
    'fecha_referencia',
    'cotizacion_id',
    'cita_id',
    'oferta_id',
    'solicitud_id',
    'orden_id',
    'conversation_id',
    'horario_por_confirmar',
    'en_edicion',
    'vehiculo_resumen',
    'vehiculo_patente',
)


def _telefono_cliente_key(raw: str) -> str:
    digits = ''.join(c for c in (raw or '') if c.isdigit())
    if len(digits) < 8:
        return ''
    if digits.startswith('569') and len(digits) >= 11:
        nacional = digits[-9:]
    elif digits.startswith('56') and len(digits) >= 11:
        nacional = digits[-9:]
    else:
        nacional = digits[-9:] if len(digits) >= 9 else digits
    if len(nacional) == 9 and nacional[0] == '9':
        return f'tel-56{nacional}'
    return f'tel-{digits}'


def _identidad_tokens(fila: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    tel = _telefono_cliente_key(str(fila.get('cliente_telefono') or ''))
    if tel:
        tokens.append(tel)
    conv = fila.get('conversation_id')
    if conv:
        tokens.append(f'conv-{conv}')
    user_id = fila.get('cliente_user_id')
    if user_id:
        tokens.append(f'user-{user_id}')
    return tokens


def _clave_canonica(tokens: set[str]) -> str:
    tels = sorted(t for t in tokens if t.startswith('tel-'))
    if tels:
        return tels[0]
    convs = sorted(t for t in tokens if t.startswith('conv-'))
    if convs:
        return convs[0]
    users = sorted(t for t in tokens if t.startswith('user-'))
    if users:
        return users[0]
    return sorted(tokens)[0]


def _vehiculo_grupo_key(fila: dict[str, Any]) -> str:
    pat = _compactar_alfanum(str(fila.get('vehiculo_patente') or '')).upper()
    if pat:
        return f'pat-{pat}'
    marca = (fila.get('vehiculo_marca') or '').strip().lower()
    modelo = (fila.get('vehiculo_modelo') or '').strip().lower()
    anio = fila.get('vehiculo_anio')
    if marca or modelo:
        return f'veh-{marca}|{modelo}|{anio or ""}'
    return 'sin-vehiculo'


def _caso_enviado(fila: dict[str, Any]) -> bool:
    raw = str(fila.get('estado_raw') or '')
    tipo = fila.get('tipo_entidad')
    if tipo == 'cotizacion_canal':
        return raw in {'enviada', 'aceptada', 'rechazada', 'expirada', 'cancelada'}
    if tipo == 'oferta':
        return raw not in {'retirada', ''}
    return False


def _caso_aceptado(fila: dict[str, Any]) -> bool:
    if str(fila.get('estado_raw') or '') == 'aceptada':
        return True
    return fila.get('estado_normalizado') in (
        'aceptado_agendado',
        'en_ejecucion',
        'completado',
    )


def _caso_rechazado(fila: dict[str, Any]) -> bool:
    return fila.get('estado_normalizado') == 'rechazado_perdido'


def _caso_abierto(fila: dict[str, Any]) -> bool:
    if fila.get('en_edicion') or fila.get('horario_por_confirmar') or fila.get('listo_para_enviar'):
        return True
    return fila.get('estado_normalizado') in (
        'nuevo',
        'cotizacion_enviada',
        'en_negociacion',
        'aceptado_agendado',
        'en_ejecucion',
    )


def _nombre_cliente_casos(casos: list[dict[str, Any]]) -> str:
    ordered = sorted(casos, key=lambda c: c.get('fecha_referencia') or '', reverse=True)
    for caso in ordered:
        nombre = (caso.get('cliente_nombre') or '').strip()
        if nombre.lower() not in _NOMBRES_GENERICOS:
            return nombre
    if ordered:
        return (ordered[0].get('cliente_nombre') or '').strip() or 'Cliente'
    return 'Cliente'


def _telefono_display_casos(casos: list[dict[str, Any]], cliente_key: str) -> str:
    if cliente_key.startswith('tel-') and len(cliente_key) > 4:
        digits = cliente_key[4:]
        return f'+{digits}' if digits.startswith('56') else digits
    for caso in sorted(casos, key=lambda c: c.get('fecha_referencia') or '', reverse=True):
        tel = (caso.get('cliente_telefono') or '').strip()
        if tel:
            return tel
    return ''


def _caso_publico(fila: dict[str, Any]) -> dict[str, Any]:
    return {k: fila.get(k) for k in _CASO_PUBLICO_KEYS}


def _payload_cliente(cliente_key: str, casos: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(casos, key=lambda c: c.get('fecha_referencia') or '', reverse=True)
    vehiculos_map: dict[str, dict[str, Any]] = {}
    vehiculos_order: list[str] = []
    for caso in ordered:
        vkey = _vehiculo_grupo_key(caso)
        if vkey not in vehiculos_map:
            vehiculos_map[vkey] = {
                'key': vkey,
                'resumen': (caso.get('vehiculo_resumen') or '').strip() or 'Sin vehículo',
                'patente': (caso.get('vehiculo_patente') or '').strip().upper(),
                'casos': [],
            }
            vehiculos_order.append(vkey)
        vehiculos_map[vkey]['casos'].append(_caso_publico(caso))
        if caso.get('vehiculo_resumen') and vehiculos_map[vkey]['resumen'] == 'Sin vehículo':
            vehiculos_map[vkey]['resumen'] = caso['vehiculo_resumen']
    origenes: list[str] = []
    for caso in ordered:
        origen = caso.get('origen')
        if origen and origen not in origenes:
            origenes.append(origen)
    conv_id = next((c.get('conversation_id') for c in ordered if c.get('conversation_id')), None)
    return {
        'cliente_key': cliente_key,
        'cliente_nombre': _nombre_cliente_casos(ordered),
        'cliente_telefono': _telefono_display_casos(ordered, cliente_key),
        'origenes': origenes,
        'vehiculos': [vehiculos_map[k] for k in vehiculos_order],
        'casos_count': len(ordered),
        'enviadas': sum(1 for c in ordered if _caso_enviado(c)),
        'aceptadas': sum(1 for c in ordered if _caso_aceptado(c)),
        'rechazadas': sum(1 for c in ordered if _caso_rechazado(c)),
        'abiertas': sum(1 for c in ordered if _caso_abierto(c)),
        'ultima_actividad': ordered[0].get('fecha_referencia') if ordered else None,
        'conversation_id': conv_id,
        'con_accion': any(_caso_abierto(c) for c in ordered),
    }


def _agrupar_filas_por_cliente(filas: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    sueltos: dict[str, list[dict[str, Any]]] = {}
    vinculados: list[dict[str, Any]] = []
    for fila in filas:
        tokens = _identidad_tokens(fila)
        if not tokens:
            key = f"caso-{fila.get('tipo_entidad')}-{fila.get('entidad_id')}"
            sueltos.setdefault(key, []).append(fila)
            continue
        for token in tokens[1:]:
            union(tokens[0], token)
        vinculados.append(fila)

    tokens_por_raiz: dict[str, set[str]] = {}
    casos_por_raiz: dict[str, list[dict[str, Any]]] = {}
    for fila in vinculados:
        tokens = _identidad_tokens(fila)
        raiz = find(tokens[0])
        casos_por_raiz.setdefault(raiz, []).append(fila)
        tokens_por_raiz.setdefault(raiz, set()).update(tokens)
    for token, p in list(parent.items()):
        tokens_por_raiz.setdefault(find(p), set()).add(token)

    agrupados: dict[str, dict[str, Any]] = {}
    for raiz, casos in casos_por_raiz.items():
        key = _clave_canonica(tokens_por_raiz.get(raiz, {raiz}))
        if key in agrupados:
            agrupados[key]['casos'].extend(casos)
        else:
            agrupados[key] = {'casos': casos}
    for key, casos in sueltos.items():
        agrupados[key] = {'casos': casos}

    return {key: _payload_cliente(key, data['casos']) for key, data in agrupados.items()}


def construir_pipeline_clientes(
    *,
    user,
    taller: Taller | None,
    origen: str | None = None,
    prioridad: str | None = None,
    miembro_taller_id: int | None = None,
    limite: int = 100,
    q: str | None = None,
) -> dict[str, Any]:
    """Lista de clientes comerciales (personas), no filas por folio."""
    if taller is None:
        return {'count': 0, 'results': [], 'resumen': {'todos': 0, 'con_accion': 0, 'cerrados': 0}}

    filas, _ = _recoger_filas_pipeline(
        user=user,
        taller=taller,
        incluir_borradores=False,
        q=q,
        miembro_taller_id=miembro_taller_id,
    )
    if origen:
        filas = [f for f in filas if f['origen'] == origen]
    if miembro_taller_id:
        filas = [
            f for f in filas
            if f.get('miembro_taller_id') in (None, miembro_taller_id)
        ]
    filas = _ordenar_filas_recientes(filas)
    filas = _dedupe_pipeline_filas(filas)
    clientes = list(_agrupar_filas_por_cliente(filas).values())
    clientes.sort(key=lambda c: c.get('ultima_actividad') or '', reverse=True)

    if q:
        clientes = [
            c
            for c in clientes
            if _fila_coincide_busqueda(
                {
                    'cliente_nombre': c.get('cliente_nombre'),
                    'cliente_telefono': c.get('cliente_telefono'),
                    'numero_publico': ' '.join(
                        caso.get('numero_publico') or ''
                        for veh in c.get('vehiculos') or []
                        for caso in veh.get('casos') or []
                    ),
                    'vehiculo_resumen': ' '.join(
                        veh.get('resumen') or '' for veh in c.get('vehiculos') or []
                    ),
                    'vehiculo_patente': ' '.join(
                        veh.get('patente') or '' for veh in c.get('vehiculos') or []
                    ),
                    'servicio_resumen': ' '.join(
                        caso.get('servicio_resumen') or ''
                        for veh in c.get('vehiculos') or []
                        for caso in veh.get('casos') or []
                    ),
                    'cotizacion_id': '',
                    'entidad_id': c.get('cliente_key'),
                },
                q,
            )
        ]

    resumen = {
        'todos': len(clientes),
        'con_accion': sum(1 for c in clientes if c.get('con_accion')),
        'cerrados': sum(1 for c in clientes if not c.get('con_accion')),
    }
    prioridad_norm = (prioridad or 'todos').strip().lower()
    if prioridad_norm == 'con_accion':
        clientes = [c for c in clientes if c.get('con_accion')]
    elif prioridad_norm == 'cerrados':
        clientes = [c for c in clientes if not c.get('con_accion')]

    results = []
    for cliente in clientes[:limite]:
        row = dict(cliente)
        row['vehiculos'] = [
            {'key': v['key'], 'resumen': v['resumen'], 'patente': v['patente']}
            for v in cliente.get('vehiculos') or []
        ]
        row.pop('con_accion', None)
        results.append(row)

    return {
        'count': len(results),
        'results': results,
        'resumen': resumen,
    }


def construir_pipeline_cliente_detalle(
    *,
    user,
    taller: Taller | None,
    cliente_key: str,
    miembro_taller_id: int | None = None,
) -> dict[str, Any] | None:
    if taller is None or not (cliente_key or '').strip():
        return None
    filas, _ = _recoger_filas_pipeline(
        user=user,
        taller=taller,
        incluir_borradores=False,
        q=None,
        miembro_taller_id=miembro_taller_id,
    )
    if miembro_taller_id:
        filas = [
            f for f in filas
            if f.get('miembro_taller_id') in (None, miembro_taller_id)
        ]
    filas = _dedupe_pipeline_filas(filas)
    agrupados = _agrupar_filas_por_cliente(filas)
    cliente = agrupados.get(cliente_key.strip())
    if cliente is None:
        return None
    payload = dict(cliente)
    payload.pop('con_accion', None)
    return payload
