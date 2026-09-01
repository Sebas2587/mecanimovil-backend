"""Envío y respuesta de cotizaciones canal."""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from mecanimovilapp.apps.chat.models import Conversation, Message
from mecanimovilapp.apps.ordenes.models import CotizacionCanal
from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.normalizar import (
    aplicar_totales_cotizacion,
    etiqueta_descuento,
    recalcular_totales,
)

logger = logging.getLogger(__name__)


def formatear_moneda_clp(valor: int | Decimal) -> str:
    n = int(valor or 0)
    return f'${n:,}'.replace(',', '.')


def payload_plantilla_whatsapp_cotizacion(cotizacion: CotizacionCanal) -> dict:
    """Componentes de plantilla UTILITY: taller, servicio, total, URL."""
    from mecanimovilapp.apps.omnichannel.services.whatsapp_templates import (
        payload_cotizacion,
    )

    taller_nombre = ''
    taller = getattr(cotizacion, 'taller', None)
    if taller is not None:
        taller_nombre = (getattr(taller, 'nombre', '') or '').strip()
    return payload_cotizacion(
        taller=taller_nombre,
        servicio=(cotizacion.servicio_nombre or '').strip() or 'tu servicio',
        total=formatear_moneda_clp(cotizacion.total_clp),
        url=(cotizacion.url_publica or '').strip() or '—',
        token=(cotizacion.token or '').strip(),
    )


def _linea_vehiculo_cotizacion(cotizacion: CotizacionCanal) -> list[str]:
    lineas = ['*Vehículo:*']
    if cotizacion.vehiculo_marca:
        lineas.append(f'Marca: {cotizacion.vehiculo_marca}')
    if cotizacion.vehiculo_modelo:
        lineas.append(f'Modelo: {cotizacion.vehiculo_modelo}')
    if cotizacion.vehiculo_anio:
        lineas.append(f'Año: {cotizacion.vehiculo_anio}')
    if cotizacion.vehiculo_cilindraje:
        lineas.append(f'Cilindraje: {cotizacion.vehiculo_cilindraje}')
    if cotizacion.vehiculo_patente:
        lineas.append(f'Patente: {cotizacion.vehiculo_patente}')
    if cotizacion.tipo_motor_label:
        lineas.append(f'Motor: {cotizacion.tipo_motor_label}')
    return lineas


def metadata_cotizacion_mensaje(cotizacion: CotizacionCanal, *, estado: str = 'enviada') -> dict:
    repuestos_meta: list[dict] = []
    for rep in cotizacion.repuestos or []:
        cant = int(rep.get('cantidad') or 1)
        precio = int(rep.get('precio_unitario_clp') or 0)
        repuestos_meta.append({
            'nombre': str(rep.get('nombre') or 'Repuesto')[:200],
            'cantidad': max(1, cant),
            'precio_unitario_clp': max(0, precio),
        })
    advertencias = [str(a).strip() for a in (cotizacion.advertencias or []) if str(a).strip()]
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
        mano_obra_lineas_publicas,
    )
    return {
        'tipo': 'cotizacion_canal',
        'cotizacion_id': cotizacion.id,
        'estado': estado,
        'servicio_nombre': cotizacion.servicio_nombre or '',
        'descripcion_problema': cotizacion.descripcion_problema or '',
        'modalidad': cotizacion.modalidad or 'taller',
        'vehiculo_marca': cotizacion.vehiculo_marca or '',
        'vehiculo_modelo': cotizacion.vehiculo_modelo or '',
        'vehiculo_anio': cotizacion.vehiculo_anio,
        'vehiculo_cilindraje': cotizacion.vehiculo_cilindraje or '',
        'vehiculo_patente': cotizacion.vehiculo_patente or '',
        'tipo_motor_label': cotizacion.tipo_motor_label or '',
        'mano_obra_lineas': mano_obra_lineas_publicas(cotizacion),
        'mano_obra_clp': int(cotizacion.mano_obra_clp or 0),
        'costo_repuestos_clp': int(cotizacion.costo_repuestos_clp or 0),
        'total_clp': int(cotizacion.total_clp or 0),
        'duracion_minutos_estimada': cotizacion.duracion_minutos_estimada,
        'repuestos': repuestos_meta,
        'advertencias': advertencias,
        # Aceptar/rechazar vive en la página pública de la cotización (url_publica),
        # no en botones interactivos de WhatsApp.
        'interactive': False,
    }


def formatear_teaser_cotizacion(cotizacion: CotizacionCanal) -> str:
    servicio = cotizacion.servicio_nombre or 'tu servicio'
    vehiculo = ' '.join(
        filter(None, [cotizacion.vehiculo_marca, cotizacion.vehiculo_modelo])
    ).strip() or 'tu vehículo'
    url = cotizacion.url_publica or ''
    folio = (cotizacion.numero_publico or '').strip()
    folio_txt = f' {folio}' if folio else ''
    if cotizacion.es_cotizacion_adicional:
        principal = ''
        orig = cotizacion.cotizacion_original
        if orig is not None:
            principal = (orig.servicio_nombre or '').strip()
        if not principal:
            cita = cotizacion.cita_origen
            det = getattr(cita, 'detalle', None) if cita is not None else None
            if det is not None:
                principal = (det.servicio_nombre or '').strip()
        contexto = principal or 'tu servicio en curso'
        from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
            es_adicional_nueva_fecha,
            formatear_slot_propuesto,
        )

        slot = formatear_slot_propuesto(cotizacion) if es_adicional_nueva_fecha(cotizacion) else ''
        fecha_txt = f' Fecha propuesta: {slot}.' if slot else ''
        if url:
            return (
                f'Te enviamos un trabajo adicional{folio_txt} encontrado durante {contexto} ({vehiculo}).'
                f'{fecha_txt} '
                f'Revísalo y responde (aceptar o rechazar) en este enlace: {url}'
            )
        return (
            f'Te enviamos un trabajo adicional{folio_txt} encontrado durante {contexto} ({vehiculo}).'
            f'{fecha_txt} '
            'Revisa los detalles y respóndenos cuando puedas.'
        )
    if url:
        return (
            f'¡Tu cotización{folio_txt} para {servicio} ({vehiculo}) está lista! '
            f'Revísala y responde (aceptar o rechazar) en este enlace: {url}'
        )
    return (
        f'¡Tu cotización{folio_txt} para {servicio} ({vehiculo}) está lista! '
        'Revisa los detalles y respóndenos cuando puedas.'
        )


def _mensaje_inbound_aceptacion(cotizacion: CotizacionCanal) -> str:
    from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
        es_adicional_nueva_fecha,
        formatear_slot_propuesto,
    )

    if es_adicional_nueva_fecha(cotizacion):
        slot = formatear_slot_propuesto(cotizacion)
        if slot:
            return f'✅ Trabajo adicional aceptado. Quedó agendado para el {slot}.'
        return '✅ Trabajo adicional aceptado. Quedó agendado en la fecha acordada.'
    return '✅ Trabajo adicional aceptado. El taller puede continuar en la misma visita.'


def formatear_resumen_cotizacion(cotizacion: CotizacionCanal) -> str:
    modalidad_label = 'Servicio a domicilio' if cotizacion.modalidad == 'domicilio' else 'Servicio en taller'
    lineas = [
        f'*Cotización — {cotizacion.servicio_nombre}*',
        modalidad_label,
        '',
    ]
    lineas.extend(_linea_vehiculo_cotizacion(cotizacion))
    if cotizacion.descripcion_problema:
        lineas.extend(['', f'*Detalle del servicio:*', cotizacion.descripcion_problema[:400]])

    repuestos = cotizacion.repuestos or []
    if repuestos:
        lineas.extend(['', '*Repuestos estimados:*'])
        for rep in repuestos:
            nombre = rep.get('nombre', 'Repuesto')
            cant = int(rep.get('cantidad') or 1)
            precio = int(rep.get('precio_unitario_clp') or 0)
            sub = cant * precio
            lineas.append(
                f'• {nombre} x{cant} ({formatear_moneda_clp(precio)} c/u): {formatear_moneda_clp(sub)}',
            )
        lineas.append(f'Subtotal repuestos: {formatear_moneda_clp(cotizacion.costo_repuestos_clp)}')

    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
        resolver_mano_obra_lineas,
    )
    mo_lineas = [
        lin for lin in resolver_mano_obra_lineas(cotizacion)
        if lin.get('monto_clp', 0) > 0
    ]
    if mo_lineas:
        lineas.extend(['', '*Mano de obra (IVA incl.):*'])
        for lin in mo_lineas:
            lineas.append(
                f'• {lin["nombre"]}: {formatear_moneda_clp(lin["monto_clp"])}',
            )
        if len(mo_lineas) > 1:
            lineas.append(
                f'Subtotal mano de obra: {formatear_moneda_clp(cotizacion.mano_obra_clp)}',
            )
    elif int(cotizacion.mano_obra_clp or 0) > 0:
        lineas.extend([
            '',
            f'Mano de obra (IVA incl.): {formatear_moneda_clp(cotizacion.mano_obra_clp)}',
        ])
    desc = int(getattr(cotizacion, 'descuento_clp', 0) or 0)
    if desc > 0:
        etiqueta = etiqueta_descuento(
            descuento_tipo=getattr(cotizacion, 'descuento_tipo', '') or '',
            descuento_alcance=getattr(cotizacion, 'descuento_alcance', '') or 'mano_obra',
            descuento_valor=getattr(cotizacion, 'descuento_valor', 0) or 0,
            descuento_clp=desc,
        )
        lineas.append(f'{etiqueta}: -{formatear_moneda_clp(desc)}')
    lineas.append(
        f'*Total estimado (IVA incluido): {formatear_moneda_clp(cotizacion.total_clp)}*',
    )
    if cotizacion.duracion_minutos_estimada:
        lineas.append(f'Duración estimada: {cotizacion.duracion_minutos_estimada} min')

    meta = cotizacion.metadata or {}
    pref = meta.get('preferencias_agenda') or {}
    if isinstance(pref, dict) and pref.get('confirmado_verbal'):
        fecha = (pref.get('fecha') or '').strip()
        hora = (pref.get('hora') or '').strip()
        nota = (pref.get('nota') or '').strip()
        partes_fecha = [p for p in (fecha, hora) if p]
        detalle = ' '.join(partes_fecha) if partes_fecha else nota
        if detalle:
            lineas.extend([
                '',
                f'*Recepción acordada con el cliente:* {detalle}',
                '(Pendiente de agendamiento formal al aceptar la cotización.)',
            ])

    lineas.extend(['', '*Condiciones:*', '• Precios referenciales. Confirme con el taller antes de agendar.'])

    if cotizacion.url_publica:
        lineas.extend(['', f'Revisar cotización: {cotizacion.url_publica}'])

    return '\n'.join(lineas)


def snapshot_desde_cotizacion(cotizacion: CotizacionCanal) -> dict:
    return {
        'servicio_nombre': cotizacion.servicio_nombre,
        'descripcion_problema': cotizacion.descripcion_problema,
        'modalidad': cotizacion.modalidad,
        'vehiculo_marca': cotizacion.vehiculo_marca,
        'vehiculo_modelo': cotizacion.vehiculo_modelo,
        'vehiculo_anio': cotizacion.vehiculo_anio,
        'vehiculo_patente': cotizacion.vehiculo_patente,
        'vehiculo_cilindraje': cotizacion.vehiculo_cilindraje,
        'tipo_motor': cotizacion.tipo_motor,
        'tipo_motor_label': cotizacion.tipo_motor_label,
        'repuestos': cotizacion.repuestos,
        'mano_obra_clp': int(cotizacion.mano_obra_clp or 0),
        'costo_repuestos_clp': int(cotizacion.costo_repuestos_clp or 0),
        'total_clp': int(cotizacion.total_clp or 0),
        'duracion_minutos_estimada': cotizacion.duracion_minutos_estimada,
        'advertencias': cotizacion.advertencias,
        'notas_internas': (cotizacion.notas_internas or '').strip(),
        'politicas_cotizacion': (cotizacion.politicas_cotizacion or '').strip(),
        'dias_validez': int(getattr(cotizacion, 'dias_validez', None) or 30),
        'descuento_tipo': (cotizacion.descuento_tipo or '') or '',
        'descuento_alcance': (cotizacion.descuento_alcance or 'mano_obra'),
        'descuento_valor': float(cotizacion.descuento_valor or 0),
        'descuento_clp': int(cotizacion.descuento_clp or 0),
        'servicios_lineas': (cotizacion.metadata or {}).get('servicios_lineas') or [],
    }


def _suma_catalogo_metadata(cotizacion: CotizacionCanal) -> int:
    meta = cotizacion.metadata or {}
    return sum(
        int(l.get('precio_catalogo_clp') or 0)
        for l in (meta.get('servicios_lineas') or [])
        if l.get('precio_desde_catalogo')
    )


def _estado_actual_para_correcciones(cotizacion: CotizacionCanal) -> dict:
    meta = cotizacion.metadata or {}
    return {
        'servicios_lineas': meta.get('servicios_lineas') or [],
        'servicio_nombre': (cotizacion.servicio_nombre or '').strip(),
        'descripcion_problema': (cotizacion.descripcion_problema or '').strip(),
        'modalidad': cotizacion.modalidad or '',
        'direccion_servicio': (cotizacion.direccion_servicio or '').strip(),
        'mano_obra_clp': int(cotizacion.mano_obra_clp or 0),
        'total_clp': int(cotizacion.total_clp or 0),
        'notas_internas': (cotizacion.notas_internas or '').strip(),
        'politicas_cotizacion': (cotizacion.politicas_cotizacion or '').strip(),
        'repuestos': cotizacion.repuestos or [],
    }


def _calcular_correcciones_taller(
    original: dict | None,
    final: dict,
) -> list[dict]:
    """Diff simple agente → humano al enviar cotización."""
    if not original:
        return []

    correcciones: list[dict] = []
    campos_simples = (
        'servicio_nombre',
        'descripcion_problema',
        'modalidad',
        'direccion_servicio',
        'mano_obra_clp',
        'total_clp',
        'notas_internas',
        'politicas_cotizacion',
    )
    for campo in campos_simples:
        val_agente = original.get(campo)
        val_humano = final.get(campo)
        if val_agente != val_humano:
            correcciones.append(
                {
                    'campo': campo,
                    'valor_agente': val_agente,
                    'valor_humano': val_humano,
                }
            )

    lineas_agente = original.get('servicios_lineas') or []
    lineas_humano = final.get('servicios_lineas') or []
    if lineas_agente != lineas_humano:
        correcciones.append(
            {
                'campo': 'servicios_lineas',
                'valor_agente': lineas_agente,
                'valor_humano': lineas_humano,
            }
        )

    rep_agente = original.get('repuestos') or []
    rep_humano = final.get('repuestos') or []
    if rep_agente != rep_humano:
        correcciones.append(
            {
                'campo': 'repuestos',
                'valor_agente': rep_agente,
                'valor_humano': rep_humano,
            }
        )

    return correcciones


def _persistir_correcciones_taller_al_enviar(cotizacion: CotizacionCanal) -> None:
    meta = dict(cotizacion.metadata or {})
    original = meta.get('propuesta_agente_original')
    if not original:
        return
    final = _estado_actual_para_correcciones(cotizacion)
    diff = _calcular_correcciones_taller(original, final)
    if diff:
        meta['correcciones_taller'] = {
            'enviado_en': timezone.now().isoformat(),
            'cambios': diff,
        }
        cotizacion.metadata = meta


_FUENTES_VERIFICADAS_EDICION = frozenset({'catalogo', 'historial', 'web', 'mercadolibre'})


def _precio_clp(rep: dict) -> int:
    try:
        return max(0, int(rep.get('precio_unitario_clp') or 0))
    except (TypeError, ValueError):
        return 0


def fusionar_repuestos_edicion(
    actuales: list,
    incoming: list,
) -> list:
    """Conserva precio/fuente ya enriquecidos si el PATCH trae un snapshot más débil.

    Evita que el autosave del editor pise líneas que la búsqueda web acaba de llenar
    (ítems previos y los recién agregados con IA).
    """
    by_id: dict[str, dict] = {}
    for rep in actuales:
        if isinstance(rep, dict) and rep.get('id'):
            by_id[str(rep['id'])] = rep

    out: list = []
    for i, inc in enumerate(incoming):
        if not isinstance(inc, dict):
            continue
        prev = by_id.get(str(inc.get('id') or ''))
        if prev is None and not inc.get('id') and i < len(actuales) and isinstance(actuales[i], dict):
            prev = actuales[i]
        if not isinstance(prev, dict):
            out.append(inc)
            continue

        fuente_prev = str(prev.get('fuente_marketplace') or '').strip().lower()
        fuente_inc = str(inc.get('fuente_marketplace') or '').strip().lower()
        precio_prev = _precio_clp(prev)
        precio_inc = _precio_clp(inc)
        keep_enriquecido = (
            fuente_prev in _FUENTES_VERIFICADAS_EDICION
            and precio_prev > 0
            and (precio_inc <= 0 or fuente_inc not in _FUENTES_VERIFICADAS_EDICION)
        )
        if not keep_enriquecido:
            out.append(inc)
            continue

        merged = dict(inc)
        for key in (
            'precio_unitario_clp',
            'fuente_marketplace',
            'proveedor_nombre',
            'marca_repuesto',
            'url_producto',
            'tienda_ml',
            'precio_estimado',
            'precio_referencia_mercado',
        ):
            if key in prev:
                merged[key] = prev[key]
        out.append(merged)
    return out


def aplicar_edicion_cotizacion(cotizacion: CotizacionCanal, data: dict) -> CotizacionCanal:
    if 'servicio_nombre' in data:
        cotizacion.servicio_nombre = str(data['servicio_nombre'] or '')[:255]
    if 'descripcion_problema' in data:
        cotizacion.descripcion_problema = str(data['descripcion_problema'] or '')
    if 'modalidad' in data and data['modalidad'] in ('taller', 'domicilio'):
        cotizacion.modalidad = data['modalidad']
    if 'direccion_servicio' in data:
        cotizacion.direccion_servicio = str(data.get('direccion_servicio') or '')[:500]
    if 'cliente_nombre' in data:
        cotizacion.cliente_nombre = str(data.get('cliente_nombre') or '')[:200]
    if 'cliente_telefono' in data:
        cotizacion.cliente_telefono = str(data.get('cliente_telefono') or '')[:20]
    if 'notas_internas' in data:
        nuevas = str(data.get('notas_internas') or '')
        previas = cotizacion.notas_internas or ''
        cotizacion.notas_internas = nuevas
        if nuevas.strip() != previas.strip():
            meta = dict(cotizacion.metadata or {})
            meta['notas_editadas_por_taller'] = True
            cotizacion.metadata = meta
    if 'politicas_cotizacion' in data:
        cotizacion.politicas_cotizacion = str(data.get('politicas_cotizacion') or '')
    if 'dias_validez' in data:
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import resolver_dias_validez

        cotizacion.dias_validez = resolver_dias_validez(
            taller=cotizacion.taller,
            dias=data.get('dias_validez'),
        )
    if 'repuestos' in data and isinstance(data['repuestos'], list):
        cotizacion.repuestos = fusionar_repuestos_edicion(
            list(cotizacion.repuestos or []),
            data['repuestos'],
        )
    from mecanimovilapp.apps.ordenes.services.asistente_cotizacion.mano_obra_lineas import (
        aplicar_mano_obra_en_edicion,
    )

    aplicar_mano_obra_en_edicion(cotizacion, data)
    if 'duracion_minutos_estimada' in data:
        val = data['duracion_minutos_estimada']
        cotizacion.duracion_minutos_estimada = int(val) if val else None
    if 'descuento_tipo' in data:
        tipo = str(data.get('descuento_tipo') or '').strip()
        cotizacion.descuento_tipo = tipo if tipo in ('monto', 'porcentaje') else ''
    if 'descuento_alcance' in data:
        alcance = str(data.get('descuento_alcance') or '').strip()
        cotizacion.descuento_alcance = alcance if alcance in ('mano_obra', 'total') else 'mano_obra'
    if 'descuento_valor' in data:
        try:
            cotizacion.descuento_valor = Decimal(str(data.get('descuento_valor') or 0))
        except Exception:
            cotizacion.descuento_valor = Decimal('0')
        if cotizacion.descuento_tipo == 'porcentaje' and cotizacion.descuento_valor > 100:
            cotizacion.descuento_valor = Decimal('100')
        if cotizacion.descuento_valor < 0:
            cotizacion.descuento_valor = Decimal('0')
    if not cotizacion.descuento_tipo:
        cotizacion.descuento_valor = Decimal('0')
    if cotizacion.es_cotizacion_adicional and (
        'ejecucion_adicional' in data or 'fecha_propuesta' in data or 'hora_propuesta' in data
    ):
        from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
            normalizar_plan_ejecucion,
        )

        modo_in = data.get('ejecucion_adicional', cotizacion.ejecucion_adicional)
        fecha_in = data['fecha_propuesta'] if 'fecha_propuesta' in data else cotizacion.fecha_propuesta
        hora_in = data['hora_propuesta'] if 'hora_propuesta' in data else cotizacion.hora_propuesta
        ejecucion, fecha_p, hora_p = normalizar_plan_ejecucion(
            ejecucion_adicional=modo_in,
            fecha_propuesta=fecha_in,
            hora_propuesta=hora_in,
        )
        cotizacion.ejecucion_adicional = ejecucion
        cotizacion.fecha_propuesta = fecha_p
        cotizacion.hora_propuesta = hora_p
    aplicar_totales_cotizacion(cotizacion)

    if 'mano_obra_clp' in data or 'mano_obra_lineas' in data:
        meta = dict(cotizacion.metadata or {})
        recargo = int(meta.get('recargo_domicilio_aplicado_clp') or 0)
        catalogo = _suma_catalogo_metadata(cotizacion)
        meta['mano_obra_manual_clp'] = max(0, int(cotizacion.mano_obra_clp or 0) - catalogo - recargo)
        cotizacion.metadata = meta

    return cotizacion


MSG_EDICION_CON_HORARIO = (
    'Esta cotización ya tiene un horario agendado. '
    'Agrega un trabajo adicional (servicio o solo repuestos) sobre la cita, '
    'sin modificar la cotización original.'
)


def cita_activa_de_cotizacion(cotizacion: CotizacionCanal):
    """Cita activa más reciente generada por esta cotización, o None."""
    return (
        cotizacion.citas_generadas.filter(estado='activa')
        .order_by('-fecha_creacion')
        .first()
    )


def _cita_activa_no_iniciada_de_cotizacion(cotizacion: CotizacionCanal):
    """Cita generada por esta cotización, activa y sin checklist en curso."""
    cita = cita_activa_de_cotizacion(cotizacion)
    if cita is None:
        return None
    inst = getattr(cita, 'checklist_instance', None)
    if inst is not None and inst.estado not in (None, '', 'PENDIENTE'):
        return None
    return cita


def cotizacion_tiene_horario_agendado(cotizacion: CotizacionCanal) -> bool:
    """True si hay cita activa con día y hora confirmados (no 'por confirmar')."""
    cita = cita_activa_de_cotizacion(cotizacion)
    if cita is None:
        return False
    if getattr(cita, 'horario_por_confirmar', False):
        return False
    return bool(getattr(cita, 'fecha_servicio', None) and getattr(cita, 'hora_servicio', None))


def cotizacion_permite_edicion_completa(cotizacion: CotizacionCanal) -> bool:
    """Misma cotización editable (ítems IA o manual) si aún no hay horario agendado."""
    if cotizacion.es_cotizacion_adicional:
        return cotizacion.estado == 'borrador'
    if cotizacion.estado in ('borrador', 'enviada'):
        return True
    if cotizacion.estado == 'aceptada':
        return not cotizacion_tiene_horario_agendado(cotizacion)
    return False


def asegurar_cotizacion_editable_para_items(cotizacion: CotizacionCanal) -> CotizacionCanal:
    """Valida edición y, si está enviada, la reabre a borrador (mismo token)."""
    if not cotizacion_permite_edicion_completa(cotizacion):
        if cotizacion_tiene_horario_agendado(cotizacion):
            raise ValueError(MSG_EDICION_CON_HORARIO)
        raise ValueError('Esta cotización ya no se puede editar.')
    if cotizacion.estado == 'enviada' and not cotizacion.es_cotizacion_adicional:
        return reabrir_cotizacion_enviada(cotizacion)
    return cotizacion


def aplicar_efecto_edicion_aceptada(
    cotizacion: CotizacionCanal,
    *,
    total_previo: int,
    cita=None,
) -> str:
    """Tras cambiar una aceptada: si el total sube, pide reconfirmación en el mismo link."""
    total_nuevo = int(cotizacion.total_clp or 0)
    meta = dict(cotizacion.metadata or {})
    meta['actualizada_tras_aceptacion'] = True
    meta['actualizada_en'] = timezone.now().isoformat()
    meta['total_previo_aceptado_clp'] = total_previo
    cotizacion.metadata = meta

    if total_nuevo > total_previo:
        cotizacion.estado = 'enviada'
        cotizacion.aceptada_en = None
        cotizacion.enviada_en = timezone.now()
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import preparar_emision_publica

        preparar_emision_publica(cotizacion)
        cotizacion.save()
        det = getattr(cita, 'detalle', None) if cita is not None else None
        if det is not None:
            det.precio_referencia = total_previo
            det.save(update_fields=['precio_referencia'])
        return 'requiere_confirmacion'

    cotizacion.save()
    det = getattr(cita, 'detalle', None) if cita is not None else None
    if det is not None:
        det.precio_referencia = total_nuevo
        det.save(update_fields=['precio_referencia'])
    return 'actualizada'


def cerrar_reapertura_taller(cotizacion: CotizacionCanal) -> None:
    """Quita el flag de edición al reenviar para que Bandeja deje 'En edición'."""
    meta = dict(cotizacion.metadata or {})
    if not meta.get('reabierta_por_taller'):
        return
    meta['reabierta_por_taller'] = False
    meta['reenviada_tras_edicion_en'] = timezone.now().isoformat()
    cotizacion.metadata = meta


@transaction.atomic
def reabrir_cotizacion_enviada(cotizacion: CotizacionCanal) -> CotizacionCanal:
    """enviada → borrador (mismo token). El cliente deja de poder aceptar hasta reenviar."""
    if cotizacion.estado != 'enviada':
        raise ValueError('Solo se puede reabrir una cotización enviada pendiente de respuesta.')
    if cotizacion.es_cotizacion_adicional:
        raise ValueError('Usa el flujo de hallazgo para trabajos adicionales.')
    meta = dict(cotizacion.metadata or {})
    meta['reabierta_por_taller'] = True
    meta['reabierta_en'] = timezone.now().isoformat()
    cotizacion.estado = 'borrador'
    cotizacion.metadata = meta
    cotizacion.save(update_fields=['estado', 'metadata', 'actualizado_en'])
    return cotizacion


@transaction.atomic
def actualizar_cotizacion_aceptada_sin_iniciar(
    cotizacion: CotizacionCanal,
    data: dict,
) -> tuple[CotizacionCanal, str]:
    """
    Actualiza cotización aceptada sin horario agendado (o con horario aún por confirmar).
    Si ya hay día/hora confirmados, hay que usar un trabajo adicional.
    - Si el total sube: pasa a enviada para que el cliente confirme el delta (mismo link).
    - Si no: mantiene aceptada y actualiza precio de referencia de la cita, si existe.
    Retorna (cotizacion, modo) donde modo es 'requiere_confirmacion' | 'actualizada'.
    """
    if cotizacion.estado != 'aceptada':
        raise ValueError('Solo aplica a cotizaciones aceptadas.')
    if cotizacion.es_cotizacion_adicional:
        raise ValueError('Los hallazgos usan cotizaciones adicionales.')
    if cotizacion_tiene_horario_agendado(cotizacion):
        raise ValueError(MSG_EDICION_CON_HORARIO)
    cita = _cita_activa_no_iniciada_de_cotizacion(cotizacion)

    total_previo = int(cotizacion.total_clp or 0)
    aplicar_edicion_cotizacion(cotizacion, data)
    modo = aplicar_efecto_edicion_aceptada(
        cotizacion,
        total_previo=total_previo,
        cita=cita,
    )
    return cotizacion, modo


@transaction.atomic
def enviar_cotizacion_canal(cotizacion: CotizacionCanal, user) -> Message:
    if cotizacion.estado not in ('borrador',):
        raise ValueError('Solo se pueden enviar cotizaciones en borrador.')
    from mecanimovilapp.apps.ordenes.services.cotizacion_adicional import (
        validar_adicional_listo_para_enviar,
    )

    validar_adicional_listo_para_enviar(cotizacion)
    conversation = cotizacion.conversation
    if conversation.type != 'OMNICHANNEL':
        raise ValueError('La cotización debe estar ligada a una conversación omnicanal.')

    aplicar_totales_cotizacion(cotizacion)
    cotizacion.save(
        update_fields=[
            'costo_repuestos_clp',
            'mano_obra_clp',
            'descuento_clp',
            'total_clp',
            'actualizado_en',
        ],
    )

    from mecanimovilapp.apps.ordenes.services.cotizacion_publica import preparar_emision_publica

    preparar_emision_publica(cotizacion)
    _persistir_correcciones_taller_al_enviar(cotizacion)
    if cotizacion.url_publica:
        meta_extra = dict(cotizacion.metadata or {})
        meta_extra['url_publica'] = cotizacion.url_publica
        cotizacion.metadata = meta_extra
        cotizacion.save(update_fields=['metadata', 'actualizado_en'])

    teaser = formatear_teaser_cotizacion(cotizacion)
    meta = metadata_cotizacion_mensaje(cotizacion, estado='enviada')
    message = Message.objects.create(
        conversation=conversation,
        sender=user,
        content=teaser,
        direction='outbound',
        channel_metadata=meta,
    )
    cotizacion.message_envio = message
    cotizacion.estado = 'enviada'
    cotizacion.enviada_en = timezone.now()
    from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
        aplicar_fecha_expiracion_publica,
    )

    aplicar_fecha_expiracion_publica(cotizacion)
    cerrar_reapertura_taller(cotizacion)
    cotizacion.save(
        update_fields=[
            'message_envio',
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

    from mecanimovilapp.apps.omnichannel.services.broadcast import (
        broadcast_to_participants,
        build_chat_payload,
    )
    from mecanimovilapp.apps.omnichannel.utils import channel_to_api_slug

    channel_slug = channel_to_api_slug(conversation.source_channel)
    sender_name = (
        f'{user.first_name or ""} {user.last_name or ""}'.strip()
        or getattr(user, 'username', '')
        or 'Taller'
    )
    payload = build_chat_payload(
        conversation=conversation,
        message=message,
        channel_slug=channel_slug,
        es_proveedor=True,
        sender_name=sender_name,
        external_contact=getattr(conversation, 'external_contact', None),
    )
    broadcast_to_participants(conversation, payload)

    try:
        from mecanimovilapp.apps.agente_ia.services.notificaciones import (
            notificar_cotizacion_enviada_agente,
        )

        notificar_cotizacion_enviada_agente(
            proveedor_user_id=user.id,
            cotizacion=cotizacion,
            conversation_id=conversation.id,
        )
    except Exception:
        logger.warning('No se pudo notificar cotización enviada cot=%s', cotizacion.id, exc_info=True)

    return message


def aplicar_plan_entrega_cotizacion(cotizacion: CotizacionCanal, plan) -> CotizacionCanal:
    meta = dict(cotizacion.metadata or {})
    meta['entrega_canal'] = plan.via
    if plan.code:
        meta['entrega_canal_motivo'] = plan.code
    else:
        meta.pop('entrega_canal_motivo', None)
    cotizacion.metadata = meta
    cotizacion.save(update_fields=['metadata', 'actualizado_en'])
    return cotizacion


def _parse_button_id(button_id: str) -> tuple[str, int] | None:
    if not button_id:
        return None
    parts = button_id.split('_')
    if len(parts) < 3:
        return None
    accion = parts[1]
    try:
        cot_id = int(parts[2])
    except ValueError:
        return None
    if accion not in ('aceptar', 'rechazar'):
        return None
    return accion, cot_id


@transaction.atomic
def procesar_respuesta_interactive_cotizacion(
    *,
    button_id: str,
    conversation: Conversation,
) -> CotizacionCanal | None:
    parsed = _parse_button_id(button_id)
    if not parsed:
        return None
    accion, cot_id = parsed
    cotizacion = CotizacionCanal.objects.select_for_update().filter(
        pk=cot_id,
        conversation=conversation,
    ).first()
    if cotizacion is None:
        logger.warning('Cotización %s no encontrada para conversación %s', cot_id, conversation.id)
        return None
    if cotizacion.estado != 'enviada':
        return cotizacion

    cita_id = None
    if accion == 'aceptar':
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            aceptar_cotizacion_publica,
            on_cotizacion_respondida,
        )

        cotizacion, cita = aceptar_cotizacion_publica(cotizacion)
        cita_id = cita.id if cita else None
        on_cotizacion_respondida(
            cotizacion,
            'aceptar',
            conversation=conversation,
            cita_id=cita_id,
        )
    else:
        from mecanimovilapp.apps.ordenes.services.cotizacion_publica import (
            on_cotizacion_respondida,
            rechazar_cotizacion_publica,
        )

        cotizacion = rechazar_cotizacion_publica(cotizacion)
        on_cotizacion_respondida(
            cotizacion,
            'rechazar',
            conversation=conversation,
        )

    if cotizacion.message_envio_id:
        meta = dict(cotizacion.message_envio.channel_metadata or {})
        meta['estado'] = cotizacion.estado
        Message.objects.filter(pk=cotizacion.message_envio_id).update(channel_metadata=meta)

    Message.objects.create(
        conversation=conversation,
        sender=None,
        content=(
            (
                _mensaje_inbound_aceptacion(cotizacion)
                if cotizacion.es_cotizacion_adicional
                else '✅ Cotización aceptada. El taller la recibió y la agendará contigo.'
            )
            if accion == 'aceptar'
            else '❌ Cotización rechazada.'
        ),
        direction='inbound',
        channel_metadata={
            'tipo': 'cotizacion_canal_respuesta',
            'cotizacion_id': cotizacion.id,
            'estado': cotizacion.estado,
            'cita_id': cita_id,
        },
    )
    return cotizacion
